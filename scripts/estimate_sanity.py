"""Sanity gates for a full-cohort `auditpace estimate` run. Structural gates only: it reads
`cases.applies`/`cases.end_ts` to check category totals and the no-end count, never `cases.breached`
(the coverage table it prints was computed by `--coverage`, which is the one evaluation-only reader).
Prints GATES: ok / FAIL."""
import sys

import pandas as pd

from auditpace.protocol import load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store

s = load_settings()
p = load_protocol()
fails = []
with Store(s.paths.processed_dir, read_only=True) as store:
    est = store.read("estimates"); al = store.read("alerts"); q = store.read("queue")
    v = store.read("verdicts"); cases = store.read("cases")
    rev = store.read("reviews") if store.exists("reviews") else pd.DataFrame(columns=["case_id", "validation_state"])
    a = est[est.segment_key == "all"].set_index("criterion_id")
    print(a[["n", "n_reviewed", "n_abstain", "n_no_end", "n_breached_system", "n_breached_legitimate", "n_breached_undetermined",
             "naive_rate", "corrected_rate", "corrected_lo", "corrected_hi", "method"]].to_string())
    total = int(a.n.sum() + a.n_abstain.sum() + a.n_no_end.sum())
    n_applicable = int(cases.applies.sum())
    if total != len(v):
        fails.append(f"category totals {total} != verdicts {len(v)}")
    if total != n_applicable:  # a partial `adjudicate --limit` run would otherwise estimate over a subset
        fails.append(f"category totals {total} != applicable cases {n_applicable}")
    no_end = int(cases[cases.applies].end_ts.isna().sum())
    if int(a.n_no_end.sum()) != no_end:
        fails.append(f"n_no_end {int(a.n_no_end.sum())} != cases without end {no_end}")
    if set(a.index) != {c.id for c in p.criteria}:
        fails.append("missing criterion rows")
    print("\nalerts:\n" + al[["kind", "criterion_id", "segment_value", "signal", "owner", "action"]].to_string(index=False))
    if al.empty or al.action.isna().any() or al.owner.isna().any():
        fails.append("alerts empty or missing action/owner")
    if (al.kind == "top_time_lost").sum() != 1:
        fails.append("top_time_lost must be exactly one row")
    reviewed = set(rev[rev.validation_state != "flagged"].case_id)
    want_q = len(v) - len(reviewed)
    if len(q) != want_q:
        fails.append(f"queue {len(q)} != {want_q}")
    if store.exists("coverage"):
        cov = store.read("coverage")
        print("\ncoverage:\n" + cov.pivot_table(index=["criterion_id", "fraction"], columns="method", values="coverage").to_string())
        # Below ~20 reviews the corrected interval collapses onto the naive one whenever none of the m reviews
        # shows a discrepancy: P = (1 - delta)^m, delta = P(Yhat != Y). H5 (delta ~ 0.21) gives 0.39/0.075/0.009 at
        # m = 4/11/20, matching the observed 0.59/0.91/>= 0.96 (full run 2026-09-16). The m >= 20 rule is calibrated
        # to this cohort; a criterion with smaller delta needs more reviews. Small-m cells are reported, not gated --
        # S7 labels the interval provisional (n_reviewed < 20 or flag set), S8 caveats it by name.
        m = (cov.fraction * cov.n).round().clip(lower=2).clip(upper=cov.n).astype(int)
        corrected = cov[cov.method == "corrected"].copy()
        corrected["m"] = m[cov.method == "corrected"]
        small = corrected[corrected.m < 20]
        if len(small):
            print("\nsmall-m (provisional):")
            for r in small.itertuples():
                print(f"small-m (provisional): {r.criterion_id} f={r.fraction} m={r.m} coverage={r.coverage}")
        gated = corrected[corrected.m >= 20]
        bad = gated[gated.coverage < 0.92]
        if len(bad):
            fails.append(f"corrected coverage < 0.92 on {len(bad)} cells (m >= 20)")
print("\nGATES:", "ok" if not fails else "FAIL " + "; ".join(fails))
sys.exit(1 if fails else 0)
