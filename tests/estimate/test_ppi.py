import math

import numpy as np
import pytest

from auditpace.estimate.ppi import Estimate, estimate_rate, naive_rate, wilson, z_for


def test_z_and_wilson_known_values():
    assert abs(z_for(0.95) - 1.959964) < 1e-5
    rate, lo, hi = wilson(50, 100, z_for(0.95))
    assert rate == 0.5 and abs(lo - 0.4038) < 1e-3 and abs(hi - 0.5962) < 1e-3
    assert all(math.isnan(x) for x in wilson(0, 0, 1.96))
    _, lo0, hi0 = wilson(0, 10, 1.96)
    assert lo0 == 0.0 and hi0 > 0
    _, lo1, hi1 = wilson(10, 10, 1.96)
    assert hi1 == 1.0 and lo1 < 1  # exact at the edges, not 1 - 1e-17


def _sim(rng, N, true_p, bias, frac):
    """Truth Bernoulli(true_p); model flips positives→negatives with prob `bias` (one-sided bias)."""
    y = rng.random(N) < true_p
    yhat = y & (rng.random(N) >= bias)  # misses some true breaches: model under-calls
    n = max(2, round(frac * N))
    idx = rng.choice(N, size=n, replace=False)
    return y, yhat, idx


@pytest.mark.parametrize("bias,frac", [(0.0, 0.05), (0.1, 0.2), (0.2, 0.2), (0.2, 1.0)])
def test_corrected_coverage_holds_and_naive_collapses_under_bias(bias, frac):
    rng = np.random.default_rng(7)
    z = z_for(0.95)
    N, true_p, sims = 2000, 0.3, 1000
    cov_c = cov_n = 0
    for _ in range(sims):
        y, yhat, idx = _sim(rng, N, true_p, bias, frac)
        truth = y.mean()
        e = estimate_rate(yhat, yhat[idx], y[idx], z)
        cov_c += e.lo <= truth <= e.hi
        n = naive_rate(yhat, z)
        cov_n += n.lo <= truth <= n.hi
    assert cov_c / sims >= 0.94, f"corrected coverage {cov_c/sims:.3f}"
    if bias >= 0.2 and frac < 1.0:
        assert cov_n / sims < 0.5, f"naive coverage {cov_n/sims:.3f} should collapse under bias"


def test_methods_and_fallbacks():
    z = z_for(0.95)
    yhat = np.array([True, False, True, False, True, False])
    y = np.array([True, False, False, False, True, False])
    full = estimate_rate(yhat, yhat, y, z)
    assert full.method == "classical" and full.rate == y.mean() and full.n_reviewed == 6
    assert full == Estimate(*wilson(int(y.sum()), 6, z), "classical", None, 6, 6)
    part = estimate_rate(yhat, yhat[:3], y[:3], z)
    assert part.method == "ppi" and 0.0 <= part.lo <= part.rate <= part.hi <= 1.0
    one = estimate_rate(yhat, yhat[:1], y[:1], z)
    assert one.method == "naive" and one.flag == "n_reviewed_insufficient" and one.rate == naive_rate(yhat, z).rate
    none = estimate_rate(yhat, yhat[:0], y[:0], z)
    assert none.method == "naive" and none.n_reviewed == 0
    empty = estimate_rate(np.array([], dtype=bool), np.array([], dtype=bool), np.array([], dtype=bool), z)
    assert math.isnan(empty.rate) and empty.n == 0


def test_ppi_clips_to_unit_interval():
    z = z_for(0.95)
    yhat = np.zeros(20, dtype=bool)
    yhat_rev, y_rev = np.zeros(5, dtype=bool), np.array([True, True, False, False, False])
    e = estimate_rate(yhat, yhat_rev, y_rev, z)
    assert e.lo >= 0.0 and e.hi <= 1.0 and e.rate == pytest.approx(0.4)
    # the point estimate too: N = 5 with one breach, overturned by one of two reviews, is 0.2 - 0.5 unclipped
    yhat = np.array([True, False, False, False, False])
    e = estimate_rate(yhat, yhat[:2], np.array([False, False]), z)
    assert e.method == "ppi" and e.rate == 0.0 and e.lo == 0.0 and e.hi <= 1.0


def test_ppi_flags_zero_observed_discrepancy():
    """Every reviewed Ŷ agrees with Y: the rectifier variance is 0, the interval is the naive one
    relabelled, and the flag says so (the small-m under-coverage mechanism, spec §9)."""
    z = z_for(0.95)
    yhat = np.array([True] * 6 + [False] * 14)
    agree = estimate_rate(yhat, yhat[:5], yhat[:5], z)
    assert agree.method == "ppi" and agree.flag == "no_discrepancy_observed" and agree.n_reviewed == 5
    assert agree.rate == pytest.approx(naive_rate(yhat, z).rate)
    disagree = estimate_rate(yhat, yhat[:5], ~yhat[:5], z)
    assert disagree.method == "ppi" and disagree.flag is None
