import pandas as pd
import pytest

from auditpace.estimate.reviews import assign_pool, latest_reviews
from auditpace.store import Store
from auditpace.workbench.reviews_writer import form_to_review, write_review

T1 = pd.Timestamp("2026-09-16 10:00:00")
T2 = pd.Timestamp("2026-09-16 10:05:00")


def test_one_partition_per_write_and_latest_wins(toy_processed, toy_protocol):
    a = write_review(toy_processed, toy_protocol, case_id="sys:H4", reviewer="dr_a", validation_state="validated",
                     human_status="breached", human_reason="not_prescribed", note=None, now=T1)
    b = write_review(toy_processed, toy_protocol, case_id="sys:H4", reviewer="dr_a", validation_state="disputed",
                     human_status="not_breached", human_reason=None, note="chart signed day 1", now=T2)
    parts = sorted((toy_processed / "reviews").glob("*.parquet"))
    assert [p.name for p in parts] == sorted([f"r_{a}.parquet", f"r_{b}.parquet"])
    with Store(toy_processed, read_only=True) as s:
        rv = s.read("reviews")
    assert len(rv) == 2 and set(rv.protocol_hash) == {toy_protocol.hash}
    lr = latest_reviews(rv)
    assert len(lr) == 1 and lr.iloc[0].review_id == b and lr.iloc[0].validation_state == "disputed"
    assert set(rv.pool) == {assign_pool("sys:H4", toy_protocol.hash, toy_protocol.review.estimation_pool_fraction)}
    assert str(rv.reviewed_ts.dtype) == "datetime64[us]"


def test_c1_invariants_raise_and_write_nothing(toy_processed, toy_protocol):
    with pytest.raises(ValueError, match="human_status required"):
        write_review(toy_processed, toy_protocol, case_id="sys:H4", reviewer="x", validation_state="disputed",
                     human_status=None, human_reason=None, note=None, now=T1)
    with pytest.raises(ValueError, match="human_reason must be null"):
        write_review(toy_processed, toy_protocol, case_id="sys:H4", reviewer="x", validation_state="validated",
                     human_status="not_breached", human_reason="not_prescribed", note=None, now=T1)
    with pytest.raises(ValueError, match="validation_state"):
        write_review(toy_processed, toy_protocol, case_id="sys:H4", reviewer="x", validation_state="maybe",
                     human_status="breached", human_reason=None, note=None, now=T1)
    assert not (toy_processed / "reviews").exists()


def test_flag_writes_null_status(toy_processed, toy_protocol):
    write_review(toy_processed, toy_protocol, case_id="leg:H4", reviewer="x", validation_state="flagged",
                 human_status=None, human_reason=None, note="ask consultant", now=T1)
    with Store(toy_processed, read_only=True) as s:
        rv = s.read("reviews")
    assert rv.human_status.isna().all() and rv.note.iloc[0] == "ask consultant"


def test_form_to_review_mapping():
    assert form_to_review("confirm", "breached", "not_prescribed", None, None) == ("validated", "breached", "not_prescribed")
    assert form_to_review("confirm", "not_breached", None, None, None) == ("validated", "not_breached", None)
    assert form_to_review("confirm", "abstain", None, None, None) == ("validated", "abstain", None)
    assert form_to_review("override", "breached", "x", "not_breached", "ignored") == ("disputed", "not_breached", None)
    assert form_to_review("override", "not_breached", None, "breached", "dna") == ("disputed", "breached", "dna")
    assert form_to_review("flag", "breached", "x", "breached", "x") == ("flagged", None, None)
    with pytest.raises(ValueError, match="action"):
        form_to_review("delete", "breached", None, None, None)
