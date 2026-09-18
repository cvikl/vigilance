"""Print verdict stats and gate on abstain / agreement / evidence. Run after `auditpace adjudicate`
(works while it runs: read-only store). Reads cases.breached and cases.true_reason - this is
evaluation, not adjudication (design spec §5 invariant applies to stages 4-5 only)."""
import json
import sys

import numpy as np
import pandas as pd

from auditpace.settings import load_settings
from auditpace.store import Store


def kappa(a: pd.Series, b: pd.Series) -> float:
    """Cohen's kappa for two boolean series (NaN when undefined)."""
    a, b = a.astype(bool).values, b.astype(bool).values
    n = len(a)
    if n == 0:
        return float("nan")
    po = (a == b).mean()
    pe = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean())
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


s = load_settings()
with Store(s.paths.processed_dir, read_only=True) as store:
    v = store.read("verdicts")
    cases = store.read("cases")

want = cases[cases.applies]
m = v.merge(want[["case_id", "breached", "true_reason", "end_ts", "hours"]], on="case_id", how="left")
print(f"verdicts={len(v)} applicable_cases={len(want)} prompt_versions={sorted(v.prompt_version.unique())} "
      f"read_versions={sorted(v.read_version.unique())} errors={v.error.notna().sum()}")

rows = []
for cid, g in m.groupby("criterion_id"):
    has_end, no_end = g[g.end_ts.notna()], g[g.end_ts.isna()]
    called = has_end[has_end.status != "abstain"]
    both = called[(called.status == "breached") & called.breached]
    rows.append({
        "criterion": cid, "n": len(g), "breached": (g.status == "breached").sum(),
        "not_breached": (g.status == "not_breached").sum(), "abstain": (g.status == "abstain").sum(),
        "abstain|end": round((has_end.status == "abstain").mean(), 3) if len(has_end) else np.nan,
        "abstain|no_end": round((no_end.status == "abstain").mean(), 3) if len(no_end) else np.nan,
        "agree": round(((called.status == "breached") == called.breached).mean(), 3) if len(called) else np.nan,
        "kappa": round(kappa(called.status == "breached", called.breached), 3) if len(called) else np.nan,
        # a null reason_tag on a breached row must count as a miss, not drop out of the mean via NA propagation
        "reason_acc": round((both.reason_tag.fillna("") == both.true_reason).mean(), 3) if len(both) else np.nan,
        "hours_ok": round(((called.hours_documented - called.hours).abs() <= 1 / 60 + 1e-9).mean(), 3) if len(called) else np.nan,
    })
print("\nper criterion:")
cols = ["criterion", "n", "breached", "not_breached", "abstain", "abstain|end", "abstain|no_end",
        "agree", "kappa", "reason_acc", "hours_ok"]
print(pd.DataFrame(rows, columns=cols).set_index("criterion").to_string())

ev = pd.DataFrame([e | {"case_id": r.case_id} for r in v.itertuples() for e in json.loads(r.evidence)])
if len(ev):
    print("\nevidence found / verified by kind:")
    print(ev.groupby("kind")[["found", "verified"]].mean().round(3).to_string())
br = m[m.status == "breached"]
print(f"\nbreached without reason_tag: {br.reason_tag.isna().mean():.3f} of {len(br)}")
called_all = m[m.status != "abstain"]
# model_status is NA only on abstain rows today (already excluded above), but fillna keeps this
# NA-safe rather than silently dropping rows from the mean if that ever changes
print(f"model_status != status: {(called_all.model_status.fillna('') != called_all.status).mean():.3f} "
      f"of {len(called_all)}")

bad = []
if set(v.case_id) != set(want.case_id) or len(v) != len(want):
    bad.append(f"case_id set differs: {len(set(want.case_id) - set(v.case_id))} missing, "
               f"{len(set(v.case_id) - set(want.case_id))} extra, {len(v) - v.case_id.nunique()} dup")
he = m[m.end_ts.notna()]
if len(he) and (he.status == "abstain").mean() > 0.10:
    bad.append(f"abstain rate on end_ts-present cases {(he.status == 'abstain').mean():.3f} > 0.10")
ca = he[he.status != "abstain"]
k = kappa(ca.status == "breached", ca.breached) if len(ca) else float("nan")
if not (k >= 0.6):
    bad.append(f"pooled kappa {k:.3f} < 0.6")
if len(ev):
    tq = ev[ev.kind.isin(["from_time", "to_time"])]
    if len(tq) and tq.found.mean() < 0.85:
        bad.append(f"time-quote found rate {tq.found.mean():.3f} < 0.85")
    if ((ev.bboxes.map(bool)) != ev.verified).any():
        bad.append("bboxes non-empty ⇔ verified violated")
q = s.paths.processed_dir / "quarantine" / "adjudicate.jsonl"
if q.exists() and q.stat().st_size:
    bad.append(f"quarantine non-empty: {q}")

print("\nGATES:", "ok" if not bad else "FAIL")
for b in bad:
    print(" -", b)
sys.exit(1 if bad else 0)
