import numpy as np
import pandas as pd

from auditpace.estimate.categorise import categorise
from auditpace.estimate.coverage import FRACTIONS, run_coverage
from auditpace.estimate.reviews import empty_reviews
from tests.estimate.conftest import toy

NOW = pd.Timestamp("2026-09-16 12:00:00")


def test_coverage_corrected_holds_and_naive_collapses_under_bias(locked_protocol):
    rng = np.random.default_rng(3)
    rows = []
    for i in range(400):
        truth = rng.random() < 0.3
        called = truth and rng.random() >= 0.5        # model misses half the true breaches
        rows.append({"pid": f"p{i}", "crit": "H5", "status": "breached" if called else "not_breached",
                     "reason": "decision_delayed", "hours": 10 if called else 2, "truth": truth})
    t = toy(rows, locked_protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], empty_reviews(), locked_protocol)
    cov = run_coverage(cf, t["cases"], locked_protocol, sims=200, seed=1, now=NOW)
    assert set(cov.fraction) == set(FRACTIONS) and set(cov.method) == {"naive", "corrected"}
    c = cov.set_index(["fraction", "method"])
    assert c.loc[(0.2, "corrected"), "coverage"] >= 0.92
    assert c.loc[(0.2, "naive"), "coverage"] < 0.2
    assert c.loc[(1.0, "corrected"), "coverage"] == 1.0 and c.loc[(1.0, "corrected"), "mean_width"] < c.loc[(0.05, "corrected"), "mean_width"]
    assert (cov.n == 400).all() and (cov.n_sims == 200).all()
