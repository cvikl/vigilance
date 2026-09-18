"""Build one Case per patient × criterion from derived events (measured, nothing planted here)."""
import numpy as np
import pandas as pd

from auditpace.protocol import Criterion


def build_cases(events: pd.DataFrame, criteria: list[Criterion]) -> pd.DataFrame:
    wide_ts = events.pivot(index="patient_id", columns="event_type", values="ts")
    wide_ht = events.pivot(index="patient_id", columns="event_type", values="has_time")
    rows = []
    for pid in wide_ts.index:
        for c in criteria:
            start = wide_ts.at[pid, c.from_] if c.from_ in wide_ts.columns else pd.NaT
            end = wide_ts.at[pid, c.to] if c.to in wide_ts.columns else pd.NaT
            applies = pd.notna(start)
            if c.applies_when and "has_event" in c.applies_when:
                ev = c.applies_when["has_event"]
                applies = applies and ev in wide_ts.columns and pd.notna(wide_ts.at[pid, ev])
            hours = (end - start) / pd.Timedelta(hours=1) if (pd.notna(start) and pd.notna(end)) else np.nan
            rows.append(
                {
                    "case_id": f"{pid}:{c.id}",
                    "patient_id": pid,
                    "criterion_id": c.id,
                    "start_ts": start,
                    "end_ts": end,
                    "hours": hours,
                    "breached": bool(hours > c.target_hours) if not np.isnan(hours) else False,
                    "applies": bool(applies),
                    "true_reason": None,
                    "start_has_time": bool(wide_ht.at[pid, c.from_]) if c.from_ in wide_ht.columns and pd.notna(start) else False,
                    "end_has_time": bool(wide_ht.at[pid, c.to]) if c.to in wide_ht.columns and pd.notna(end) else False,
                }
            )
    df = pd.DataFrame(rows)
    for col in ("start_ts", "end_ts"):
        df[col] = pd.to_datetime(df[col]).astype("datetime64[us]")
    return df
