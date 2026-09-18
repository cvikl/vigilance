"""Organisation funnel plot per criterion: 2σ alert / 3σ alarm limits around the pooled rate. Spec §6."""
import math

import pandas as pd

from auditpace.estimate.ppi import z_for
from auditpace.estimate.segments import CriterionArrays, cell_rates, criterion_cells
from auditpace.protocol import Protocol


def _clip(x: float) -> float:
    return x if math.isnan(x) else min(1.0, max(0.0, x))


def limits(p: float, n: int) -> dict:
    sd = math.sqrt(p * (1 - p) / n) if n > 0 and not math.isnan(p) and 0.0 <= p <= 1.0 else math.nan
    return {"alert_lo": _clip(p - 2 * sd), "alert_hi": _clip(p + 2 * sd), "alarm_lo": _clip(p - 3 * sd), "alarm_hi": _clip(p + 3 * sd)}


def signal_for(rate: float, lim: dict) -> str:
    if rate is None or math.isnan(rate) or any(math.isnan(v) for v in lim.values()):
        return "none"
    if rate > lim["alarm_hi"]:
        return "alarm_high"
    if rate > lim["alert_hi"]:
        return "alert_high"
    if rate < lim["alarm_lo"]:
        return "alarm_low"
    if rate < lim["alert_lo"]:
        return "alert_low"
    return "none"


def centre_of(estimates: pd.DataFrame, cid: str) -> float:
    row = estimates[(estimates.criterion_id == cid) & (estimates.segment_key == "all")]
    return float(row.corrected_rate.iloc[0]) if len(row) else math.nan


def build_funnel(cf: pd.DataFrame, estimates: pd.DataFrame, protocol: Protocol, now: pd.Timestamp) -> pd.DataFrame:
    z = z_for(protocol.review.confidence)
    rows = []
    for c in protocol.criteria:
        sub = cf[cf.criterion_id == c.id].reset_index(drop=True)
        if sub.empty:
            continue
        centre = centre_of(estimates, c.id)
        crit = CriterionArrays(sub, protocol, c.id)
        for org, idx in criterion_cells(sub, "organization"):
            a = crit.cell(idx)
            n = a.n
            suppressed = n < protocol.suppress_below
            _, e = cell_rates(a, z)
            lim = limits(centre, n)
            rate, lo, hi = (math.nan,) * 3 if suppressed else (e.rate, e.lo, e.hi)
            rows.append({"criterion_id": c.id, "organization_id": str(org), "n": n, "rate": rate, "lo": lo, "hi": hi,
                         "method": e.method, "centre": centre, **lim,
                         "signal": "none" if suppressed else signal_for(rate, lim), "suppressed": suppressed,
                         "computed_ts": now})
    return pd.DataFrame(rows)
