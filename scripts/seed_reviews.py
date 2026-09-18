"""Pre-populate `reviews` for rehearsal so a live override visibly moves the corrected interval.

Writes `per_criterion` validated reviews per criterion with human_status taken from `cases.breached`
(structured truth) and human_reason from `cases.true_reason`, reviewer="seed". This is the one place
outside coverage.py that reads the truth columns; it is a rehearsal aid, not a stage. Every review goes
through `write_review` so pooling and dtypes match the UI's. Cases listed in --exclude stay unreviewed.
"""
import argparse
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from auditpace.protocol import Protocol, load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store
from auditpace.workbench.reviews_writer import write_review


def read_exclude(path: Path | None) -> set[str]:
    if path is None or not Path(path).exists():
        return set()
    return {ln.strip() for ln in Path(path).read_text().splitlines() if ln.strip() and not ln.startswith("#")}


def seed(processed_dir: Path, protocol: Protocol, per_criterion: int, seed: int, exclude: set[str],
        wipe: bool = False) -> dict[str, int]:
    processed_dir = Path(processed_dir)
    if wipe and (processed_dir / "reviews").exists():
        shutil.rmtree(processed_dir / "reviews")
    with Store(processed_dir, read_only=True) as store:
        v = store.sql("select case_id, criterion_id, status from verdicts")
        cases = store.sql("select case_id, end_ts, breached, true_reason from cases")
    df = v.merge(cases, on="case_id")
    df = df[(df.status != "abstain") & df.end_ts.notna() & ~df.case_id.isin(exclude)]
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2026-09-16 09:00:00")
    counts: dict[str, int] = {}
    reasons = {c.id: set(c.reasons) for c in protocol.criteria}
    for crit, grp in df.groupby("criterion_id", sort=True):
        ids = sorted(grp.case_id)
        pick = list(rng.choice(ids, size=min(per_criterion, len(ids)), replace=False)) if ids else []
        truth = grp.set_index("case_id")
        for i, cid in enumerate(pick):
            breached = bool(truth.loc[cid, "breached"])
            reason = truth.loc[cid, "true_reason"] if breached else None
            reason = reason if reason in reasons[crit] else ("other" if breached else None)
            write_review(processed_dir, protocol, case_id=cid, reviewer="seed", validation_state="validated",
                        human_status="breached" if breached else "not_breached", human_reason=reason,
                        note="seeded from structured truth for rehearsal", now=t0 + pd.Timedelta(seconds=i))
        counts[crit] = len(pick)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-criterion", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--exclude", type=Path, default=Path("docs/demo_cases.txt"))
    ap.add_argument("--wipe", action="store_true", help="delete data/processed/reviews/ first")
    ap.add_argument("--protocol", type=Path, default=Path("protocol.yaml"))
    a = ap.parse_args()
    s = load_settings()
    p = load_protocol(a.protocol)
    counts = seed(s.paths.processed_dir, p, a.per_criterion, a.seed, read_exclude(a.exclude), wipe=a.wipe)
    for crit, n in counts.items():
        print(f"{crit}: {n} seed reviews", flush=True)
    from auditpace.estimate.compute import compute_all
    with Store(s.paths.processed_dir, read_only=True) as store:
        est = compute_all(store, p)["estimates"]
    est = est[est.segment_key == "all"][["criterion_id", "n_reviewed", "method", "flag"]]
    print(est.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
