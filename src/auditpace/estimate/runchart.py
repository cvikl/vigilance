"""Weekly run chart per criterion (ISO week of `cases.start_ts`) with control limits. Spec §6."""
import math

import pandas as pd

from auditpace.estimate.funnel import centre_of, limits, signal_for
from auditpace.estimate.ppi import z_for
from auditpace.estimate.segments import CriterionArrays, cell_rates
from auditpace.protocol import Protocol


def build_runchart(cf: pd.DataFrame, estimates: pd.DataFrame, protocol: Protocol, now: pd.Timestamp) -> pd.DataFrame:
    z = z_for(protocol.review.confidence)
    rows = []
    for c in protocol.criteria:
        sub = cf[cf.criterion_id == c.id].reset_index(drop=True)
        if sub.empty:
            continue
        centre = centre_of(estimates, c.id)
        crit = CriterionArrays(sub, protocol, c.id)
        crit_rows = []
        weeks = sub.groupby(["week", "week_start"], sort=True).indices
        for (week, week_start) in sorted(weeks):
            a = crit.cell(weeks[(week, week_start)])
            n = a.n
            suppressed = n < protocol.suppress_below
            _, e = cell_rates(a, z)
            lim = limits(centre, n)
            rate, lo, hi = (math.nan,) * 3 if suppressed else (e.rate, e.lo, e.hi)
            crit_rows.append({"criterion_id": c.id, "week": week, "week_start": week_start, "n": n, "rate": rate,
                              "lo": lo, "hi": hi, "method": e.method, "centre": centre,
                              "alert_hi": lim["alert_hi"], "alarm_hi": lim["alarm_hi"],
                              "signal": "none" if suppressed else signal_for(rate, lim), "latest": False,
                              "suppressed": suppressed, "computed_ts": now})
        for r in reversed(crit_rows):
            if not r["suppressed"]:
                r["latest"] = True
                break
        rows.extend(crit_rows)
    return pd.DataFrame(rows)
