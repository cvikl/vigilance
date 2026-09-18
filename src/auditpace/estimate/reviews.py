"""The `reviews` table: the clinician's judgement per case (S7 writes, S6 reads). Spec §3."""
import hashlib

import pandas as pd

REVIEW_COLUMNS = [
    "review_id", "case_id", "reviewer", "validation_state", "human_status", "human_reason",
    "note", "pool", "reviewed_ts", "protocol_hash",
]
STATES = {"validated", "disputed", "flagged"}
STATUSES = {"breached", "not_breached", "abstain"}
POOLS = {"estimation", "tuning"}


def assign_pool(case_id: str, protocol_hash: str, fraction: float) -> str:
    """Deterministic estimation/tuning split fixed before any review is written."""
    h = hashlib.sha256(f"{case_id}{protocol_hash}".encode()).hexdigest()
    u = int(h[:8], 16) / 2**32
    return "estimation" if u < fraction else "tuning"


def empty_reviews() -> pd.DataFrame:
    return review_frame([])


def review_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=REVIEW_COLUMNS)
    bad = set(df.validation_state.dropna()) - STATES
    if bad:
        raise ValueError(f"validation_state must be one of {sorted(STATES)}, got {sorted(bad)}")
    bad = set(df.human_status.dropna()) - STATUSES
    if bad:
        raise ValueError(f"human_status must be one of {sorted(STATUSES)}, got {sorted(bad)}")
    bad = set(df.pool.dropna()) - POOLS
    if bad:
        raise ValueError(f"pool must be one of {sorted(POOLS)}, got {sorted(bad)}")
    # rubric C1: a review never lets S6 impute a status -- a non-flagged review must carry the
    # reviewer's own call, and a reason only accompanies a breached call
    n = int((df.human_status.isna() & (df.validation_state != "flagged")).sum())
    if n:
        raise ValueError(f"human_status required unless validation_state is 'flagged' ({n} row(s))")
    n = int((df.human_reason.notna() & (df.human_status != "breached")).sum())
    if n:
        raise ValueError(f"human_reason must be null unless human_status is 'breached' ({n} row(s))")
    df["reviewed_ts"] = pd.to_datetime(df.reviewed_ts).astype("datetime64[us]")
    for col in ("review_id", "case_id", "reviewer", "validation_state", "human_status", "human_reason",
                "note", "pool", "protocol_hash"):
        df[col] = df[col].astype(object).where(df[col].notna(), None).astype("string")
    return df


def latest_reviews(reviews: pd.DataFrame) -> pd.DataFrame:
    """One row per case: the review with the latest `reviewed_ts` (ties → last written)."""
    if reviews.empty:
        return reviews.copy()
    return (reviews.sort_values(["reviewed_ts"], kind="stable").groupby("case_id", as_index=False).tail(1)
            .reset_index(drop=True))
