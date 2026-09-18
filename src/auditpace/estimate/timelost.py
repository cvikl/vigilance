"""Hours lost over target on stalled (system-class) breaches, per criterion and organisation. Spec §6."""
import math

import pandas as pd


def _agg(sysr: pd.DataFrame, cells: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """One row per cell in `cells` (criterion, or criterion × organisation) with the system-breach
    aggregates from `sysr`; a cell with no system breach keeps n = 0, hours 0, median NaN."""
    g = sysr.groupby(by, sort=False).excess_hours
    agg = pd.DataFrame({"n_breached_system": g.size(), "hours_lost": g.sum(), "median_excess_h": g.median()})
    out = cells.join(agg, on=by)
    out["n_breached_system"] = out.n_breached_system.fillna(0).astype(int)
    out["hours_lost"] = out.hours_lost.fillna(0.0).astype(float)
    out["median_excess_h"] = out.median_excess_h.astype(float)
    return out


def build_timelost(cf: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    sysr = cf[cf.category == "breached_system"]
    crit = pd.DataFrame({"criterion_id": sorted(cf.criterion_id.unique())})
    crit = _agg(sysr, crit.assign(organization_id="all"), ["criterion_id"])
    pairs = cf[["criterion_id", "organization"]].drop_duplicates().sort_values(["criterion_id", "organization"])
    org = _agg(sysr, pairs.reset_index(drop=True), ["criterion_id", "organization"])
    org["organization_id"] = org.pop("organization").astype(str)
    cols = ["criterion_id", "organization_id", "n_breached_system", "hours_lost", "median_excess_h"]
    df = (pd.concat([crit[cols].assign(_o=0), org[cols].assign(_o=1)])
          .sort_values(["criterion_id", "_o", "organization_id"], kind="stable").drop(columns="_o").reset_index(drop=True))
    df["rank"] = math.nan
    order = df[df.organization_id == "all"].sort_values(["hours_lost", "criterion_id"], ascending=[False, True]).index
    df.loc[order, "rank"] = range(1, len(order) + 1)
    df["descriptive"] = True
    df["computed_ts"] = now
    return df
