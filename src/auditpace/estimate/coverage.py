"""Coverage experiment (evaluation only — reads `cases.breached`): does the interval contain the
true rate, naive vs corrected, at each review fraction? Spec §9."""
import numpy as np
import pandas as pd

from auditpace.estimate.ppi import estimate_rate, naive_rate, z_for
from auditpace.protocol import Protocol

FRACTIONS = (0.02, 0.05, 0.1, 0.2, 0.5, 1.0)


def run_coverage(cf: pd.DataFrame, cases: pd.DataFrame, protocol: Protocol, sims: int = 500, seed: int = 42,
                 fractions=FRACTIONS, now: pd.Timestamp | None = None) -> pd.DataFrame:
    now = now if now is not None else pd.Timestamp.now("UTC").tz_localize(None)
    z = z_for(protocol.review.confidence)
    truth_by_case = dict(zip(cases.case_id, cases.breached.astype(bool)))
    rng = np.random.default_rng(seed)
    rows = []
    for cid, sub in cf.groupby("criterion_id", sort=True):
        est = sub[sub.estimable]
        N = len(est)
        if N < 2:
            continue
        yhat = est.yhat.to_numpy(dtype=bool)
        y = np.array([truth_by_case[c] for c in est.case_id], dtype=bool)
        true_rate = y.mean()
        for f in fractions:
            m = min(N, max(2, round(f * N)))
            hit = {"naive": 0, "corrected": 0}
            width = {"naive": 0.0, "corrected": 0.0}
            for _ in range(sims):
                idx = rng.choice(N, size=m, replace=False)
                nv = naive_rate(yhat, z)
                cv = estimate_rate(yhat, yhat[idx], y[idx], z)
                for k, e in (("naive", nv), ("corrected", cv)):
                    hit[k] += e.lo <= true_rate <= e.hi
                    width[k] += e.hi - e.lo
            for k in ("naive", "corrected"):
                rows.append({"criterion_id": cid, "fraction": f, "method": k, "coverage": hit[k] / sims,
                             "mean_width": width[k] / sims, "n_sims": sims, "n": N, "computed_ts": now})
    return pd.DataFrame(rows)
