"""Derive PathwayEvents (first occurrence per patient) from structured tables per protocol rules."""
import pandas as pd

from auditpace.cohort.source import SyntheaSource
from auditpace.protocol import EventRule

_ID_COL = {
    "patients": "Id",
    "encounters": "Id",
    "conditions": "ENCOUNTER",
    "procedures": "ENCOUNTER",
    "medications": "ENCOUNTER",
    "observations": "ENCOUNTER",
}
_TS_COL = {
    "patients": "DEATHDATE",
    "encounters": "START",
    "conditions": "START",
    "procedures": "DATE",
    "medications": "START",
    "observations": "DATE",
}
_PID_COL = {"patients": "Id"}


def _first_per_patient(df: pd.DataFrame, ts_col: str) -> pd.DataFrame:
    """Whole-row first occurrence per patient_id, ordered by ts_col.

    Unlike `groupby("patient_id").first()`, which takes the first *non-null* value
    independently per column, this keeps the earliest row intact so a null
    `source_row_id`/`organization_id` on the earliest row isn't spliced with a value
    from a later row.
    """
    return df.sort_values(ts_col).drop_duplicates("patient_id", keep="first").reset_index(drop=True)


def _where(rule: EventRule) -> str:
    conds = []
    if rule.code is not None:
        codes = rule.code if isinstance(rule.code, list) else [rule.code]
        conds.append("CODE in (" + ",".join(f"'{c}'" for c in codes) + ")")
    if rule.description_contains:
        conds.append(f"lower(DESCRIPTION) like '%{rule.description_contains.lower()}%'")
    if rule.class_:
        cls = rule.class_ if isinstance(rule.class_, list) else [rule.class_]
        conds.append("ENCOUNTERCLASS in (" + ",".join(f"'{c}'" for c in cls) + ")")
    return " and ".join(conds) or "true"


def _one_rule(src: SyntheaSource, name: str, rule: EventRule, ids: str) -> pd.DataFrame:
    t = rule.table
    pid = _PID_COL.get(t, "PATIENT")
    ts = "STOP" if rule.field == "stop" else ("DEATHDATE" if rule.field == "deathdate" else _TS_COL[t])
    df = src.sql(
        f"""select {pid} as patient_id, {ts} as ts, '{t}' as source_table, cast({_ID_COL[t]} as varchar) as source_row_id
            from {t} where {pid} in ({ids}) and {_where(rule)} and {ts} is not null"""
    )
    df["event_type"] = name
    df["has_time"] = t == "encounters"
    return df


def derive_events(src: SyntheaSource, events: dict[str, EventRule], patient_ids: list[str]) -> pd.DataFrame:
    ids = ",".join(f"'{p}'" for p in patient_ids)
    frames: dict[str, pd.DataFrame] = {}
    for name, rule in events.items():
        if rule.after:
            continue
        df = _one_rule(src, name, rule, ids)
        frames[name] = _first_per_patient(df, "ts")
    for name, rule in events.items():
        if not rule.after:
            continue
        base = frames[rule.after][["patient_id", "ts"]].rename(columns={"ts": "after_ts"})
        df = _one_rule(src, name, rule, ids).merge(base, on="patient_id")
        df = df[df.ts > df.after_ts].drop(columns="after_ts")
        frames[name] = _first_per_patient(df, "ts")
    cols = ["patient_id", "event_type", "ts", "source_table", "source_row_id", "has_time"]
    out = pd.concat(frames.values(), ignore_index=True) if frames else pd.DataFrame(columns=cols)
    out["ts"] = pd.to_datetime(out["ts"]).astype("datetime64[us]")
    return out[cols]


def drop_post_mortem(events: pd.DataFrame, patients: pd.DataFrame) -> pd.DataFrame:
    """Remove events dated after the patient's death day. Synthea keeps scheduling encounters
    for dead patients; `deathdate` is date-only, so anything on the death day itself is kept.
    The `died` event is never dropped."""
    death = patients.set_index("patient_id").deathdate
    cap = events.patient_id.map(death)
    cap = pd.to_datetime(cap).dt.normalize() + pd.Timedelta(hours=23, minutes=59)
    keep = cap.isna() | (events.ts <= cap) | (events.event_type == "died")
    return events[keep].reset_index(drop=True)


def organisation_of(src: SyntheaSource, patient_ids: list[str], admitted_code: int = 1505002) -> pd.DataFrame:
    ids = ",".join(f"'{p}'" for p in patient_ids)
    df = src.sql(
        f"""select PATIENT as patient_id, ORGANIZATION as organization_id, START from encounters
            where PATIENT in ({ids}) and CODE = '{admitted_code}' order by START"""
    )
    return _first_per_patient(df, "START")[["patient_id", "organization_id"]]
