import pandas as pd
import pytest

from auditpace.estimate.reviews import (
    REVIEW_COLUMNS,
    assign_pool,
    empty_reviews,
    latest_reviews,
    review_frame,
)

H = "83174236e1209a2c64284626d213ffee57c1bec681193228446d1b630d2150d7"


def test_assign_pool_is_deterministic_and_near_fraction():
    ids = [f"p{i}:H1" for i in range(10_000)]
    pools = [assign_pool(c, H, 0.8) for c in ids]
    assert pools == [assign_pool(c, H, 0.8) for c in ids]
    share = sum(p == "estimation" for p in pools) / len(pools)
    assert 0.77 < share < 0.83
    assert assign_pool("x:H1", H, 1.0) == "estimation" and assign_pool("x:H1", H, 0.0) == "tuning"


def test_review_frame_types_and_validation():
    df = review_frame([
        {"review_id": "r1", "case_id": "a:H1", "reviewer": "dr", "validation_state": "validated",
         "human_status": "breached", "human_reason": "swab_delay", "note": None, "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": H},
        {"review_id": "r2", "case_id": "b:H1", "reviewer": "dr", "validation_state": "flagged",
         "human_status": None, "human_reason": None, "note": "ask consultant", "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:01:00", "protocol_hash": H},
    ])
    assert list(df.columns) == REVIEW_COLUMNS
    assert str(df.reviewed_ts.dtype) == "datetime64[us]"
    assert pd.isna(df.human_status.iloc[1]) and df.human_status.dtype == "string"
    with pytest.raises(ValueError, match="validation_state"):
        review_frame([{**df.iloc[0].to_dict(), "validation_state": "maybe"}])
    with pytest.raises(ValueError, match="human_status"):
        review_frame([{**df.iloc[0].to_dict(), "human_status": "yes"}])
    assert list(empty_reviews().columns) == REVIEW_COLUMNS and len(empty_reviews()) == 0


def test_review_frame_never_lets_a_status_be_imputed():
    """Rubric C1: a non-flagged review without the reviewer's call would make categorise treat the
    null as `not_breached`; a reason on a non-breached call is likewise refused."""
    base = {"review_id": "r1", "case_id": "a:H1", "reviewer": "dr", "human_reason": None, "note": None,
            "pool": "estimation", "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": H}
    for state in ("validated", "disputed"):
        with pytest.raises(ValueError, match="human_status required unless validation_state is 'flagged'"):
            review_frame([{**base, "validation_state": state, "human_status": None}])
    for status in ("not_breached", "abstain"):
        with pytest.raises(ValueError, match="human_reason must be null unless human_status is 'breached'"):
            review_frame([{**base, "validation_state": "disputed", "human_status": status, "human_reason": "swab_delay"}])
    with pytest.raises(ValueError, match="human_reason must be null"):
        review_frame([{**base, "validation_state": "flagged", "human_status": None, "human_reason": "swab_delay"}])
    ok = review_frame([{**base, "validation_state": "flagged", "human_status": None},
                       {**base, "review_id": "r2", "validation_state": "validated", "human_status": "not_breached"},
                       {**base, "review_id": "r3", "validation_state": "disputed", "human_status": "abstain"},
                       {**base, "review_id": "r4", "validation_state": "validated", "human_status": "breached", "human_reason": "swab_delay"}])
    assert len(ok) == 4


def test_latest_review_wins():
    df = review_frame([
        {"review_id": "r1", "case_id": "a:H1", "reviewer": "dr", "validation_state": "validated",
         "human_status": "breached", "human_reason": None, "note": None, "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": H},
        {"review_id": "r2", "case_id": "a:H1", "reviewer": "dr", "validation_state": "disputed",
         "human_status": "not_breached", "human_reason": None, "note": None, "pool": "estimation",
         "reviewed_ts": "2026-09-16T11:00:00", "protocol_hash": H},
    ])
    latest = latest_reviews(df)
    assert len(latest) == 1 and latest.iloc[0].review_id == "r2"
    assert latest_reviews(empty_reviews()).empty
