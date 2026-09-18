"""Breach-rate estimators: naive (model only), classical (reviews only), prediction-powered
(Angelopoulos et al., Science 2023, mean estimator). Spec §5."""
import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np


def z_for(confidence: float) -> float:
    return NormalDist().inv_cdf(0.5 + confidence / 2)


def wilson(k: int, n: int, z: float) -> tuple[float, float, float]:
    if n == 0:
        return math.nan, math.nan, math.nan
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    lo = 0.0 if k == 0 else max(0.0, centre - half)   # exact bounds at the edges (no 1e-17 noise)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return p, lo, hi


@dataclass(frozen=True)
class Estimate:
    rate: float
    lo: float
    hi: float
    method: str          # naive | classical | ppi
    flag: str | None     # n_reviewed_insufficient | no_discrepancy_observed | None
    n: int
    n_reviewed: int


def naive_rate(yhat_all: np.ndarray, z: float) -> Estimate:
    yhat_all = np.asarray(yhat_all, dtype=bool)
    rate, lo, hi = wilson(int(yhat_all.sum()), len(yhat_all), z)
    return Estimate(rate, lo, hi, "naive", None, len(yhat_all), 0)


def estimate_rate(yhat_all: np.ndarray, yhat_rev: np.ndarray, y_rev: np.ndarray, z: float) -> Estimate:
    """Corrected estimate: classical when every case is reviewed, PPI when 2 <= n < N, naive
    (flagged) when fewer than two reviews exist.

    PPI with no discrepancy among the n reviews (every Ŷ_rev == Y_rev) has a zero rectifier variance,
    so its interval is the naive interval relabelled -- flagged `no_discrepancy_observed` (spec §9).
    With δ = P(Ŷ ≠ Y) that happens with probability (1 − δ)^n, which is why few reviews under-cover."""
    yhat_all = np.asarray(yhat_all, dtype=bool)
    yhat_rev = np.asarray(yhat_rev, dtype=bool)
    y_rev = np.asarray(y_rev, dtype=bool)
    N, n = len(yhat_all), len(y_rev)
    if N == 0:
        return Estimate(math.nan, math.nan, math.nan, "naive", None, 0, 0)
    if n >= N:
        rate, lo, hi = wilson(int(y_rev.sum()), n, z)
        return Estimate(rate, lo, hi, "classical", None, N, n)
    if n < 2:
        base = naive_rate(yhat_all, z)
        return Estimate(base.rate, base.lo, base.hi, "naive", "n_reviewed_insufficient", N, n)
    d = yhat_rev.astype(float) - y_rev.astype(float)
    rate = float(yhat_all.mean() - d.mean())
    var = float(yhat_all.astype(float).var(ddof=1) / N + d.var(ddof=1) / n)  # N > n >= 2 here
    half = z * math.sqrt(max(var, 0.0))
    flag = "no_discrepancy_observed" if not d.any() else None
    # the mean estimator is unbounded at small n (e.g. N = 5, one overturned breach in 2 reviews gives
    # 0.2 - 0.5); a proportion is clipped to [0, 1] like its interval, so the funnel's sqrt(p(1-p)) is defined
    lo, hi = max(0.0, rate - half), min(1.0, rate + half)
    return Estimate(min(1.0, max(0.0, rate)), lo, hi, "ppi", flag, N, n)
