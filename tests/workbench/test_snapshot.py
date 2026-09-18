import pandas as pd
import pytest

from auditpace.estimate.compute import StaleTable
from auditpace.estimate.reviews import review_frame
from auditpace.store import Store
from auditpace.workbench.snapshot import Snapshot

NOW = pd.Timestamp("2026-09-16 12:00:00")


def test_load_holds_every_frame_and_no_truth_columns(snapshot):
    for name in ("estimates", "funnel", "runchart", "timelost", "alerts", "queue",
                 "verdicts", "patients", "reviews", "pages", "documents"):
        assert name in snapshot.frames, name
    assert "cases" not in snapshot.frames  # structured timing / truth never reaches the UI (Task 12 ruling)
    assert snapshot.loaded_ts == NOW
    assert snapshot.frames["reviews"].empty


def test_progress_counts_non_flagged_latest_reviews(toy_processed, toy_protocol):
    h = toy_protocol.hash
    rows = [
        {"review_id": "a", "case_id": "sys:H4", "reviewer": "x", "validation_state": "validated",
         "human_status": "breached", "human_reason": "not_prescribed", "note": None, "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": h},
        {"review_id": "b", "case_id": "leg:H4", "reviewer": "x", "validation_state": "flagged",
         "human_status": None, "human_reason": None, "note": "?", "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:01:00", "protocol_hash": h},
    ]
    with Store(toy_processed) as s:
        s.write_part("reviews", "r_a", review_frame(rows), h)
    snap = Snapshot.load(toy_processed, toy_protocol, now=NOW)
    reviewed, total = snap.progress()
    assert total == len(snap.frames["verdicts"]) == 21
    assert reviewed == 1


def test_page_resolves_to_existing_file(snapshot, toy_processed):
    p = snapshot.page("sys:ward_note:p1")
    assert p == toy_processed / "pages" / "b0000" / "sys:ward_note_p1.jpg" and p.exists()
    with pytest.raises(KeyError):
        snapshot.page("nope")


def test_criterion_lookup(snapshot):
    assert snapshot.criterion("H4").target_hours == 24
    with pytest.raises(KeyError):
        snapshot.criterion("H9")


def test_stale_reviews_raise(toy_processed, toy_protocol):
    rows = [{"review_id": "z", "case_id": "sys:H4", "reviewer": "x", "validation_state": "validated",
             "human_status": "breached", "human_reason": "not_prescribed", "note": None, "pool": "estimation",
             "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": "deadbeef"}]
    with Store(toy_processed) as s:
        s.write_part("reviews", "r_z", review_frame(rows), "deadbeef")
    with pytest.raises(StaleTable):
        Snapshot.load(toy_processed, toy_protocol, now=NOW)


def test_missing_verdicts_raise(tmp_path, toy_protocol):
    (tmp_path / "empty").mkdir()
    with pytest.raises(FileNotFoundError):
        Snapshot.load(tmp_path / "empty", toy_protocol, now=NOW)


from auditpace.workbench.snapshot import CaseView, Evidence


def test_queue_rows_follow_queue_order_and_carry_joined_fields(snapshot):
    q = snapshot.queue_rows()
    assert list(q.case_id) == list(snapshot.frames["queue"].case_id)
    assert q.iloc[-1].category == "abstain_no_end" and q.iloc[-1].priority == 0
    dis = q.set_index("case_id").loc["dis:H4"]
    assert dis.model_status == "not_breached" and dis.status == "breached"
    assert dis.target_hours == 24 and dis.hours == 40 and dis.organization_id == "orgB"
    assert "model call ≠ computed status" in dis.priority_reason
    unv = q.set_index("case_id").loc["unv:H4"]
    assert bool(unv.any_unverified) and unv.first_quote == "q"
    assert not bool(dis.any_unverified)
    abs_row = q.set_index("case_id").loc["abs:H2"]
    assert abs_row.model_status is None and abs_row.reason_tag is None
    assert abs_row.hours is None  # verdicts.hours_documented, never the structured cases.hours


def test_no_end_rows_sort_after_other_priority_zero_rows(snapshot):
    """Once reviews accumulate, unflagged pending rows also carry priority 0 with an empty reason (the
    seeded-store state); the no-end block must still close the queue rather than interleave."""
    from dataclasses import replace
    q = snapshot.frames["queue"].copy()
    q.loc[q.case_id == "q0:H6", ["priority", "priority_reason"]] = [0.0, ""]
    q.loc[q.case_id == "abs:H2", ["priority", "priority_reason"]] = [0.0, ""]
    snap = replace(snapshot, frames={**snapshot.frames, "queue": q})
    rows = snap.queue_rows()
    ids = list(rows.case_id)
    assert rows.set_index("case_id").loc["q0:H6"].priority == 0
    assert ids.index("q0:H6") < ids.index("noend:H6") and ids.index("abs:H2") < ids.index("noend:H6")
    assert ids[-1] == "noend:H6"
    zeros = rows[rows.priority == 0]
    assert list(zeros.category)[-1] == "abstain_no_end" and list(zeros.case_id) == ["abs:H2", "q0:H6", "noend:H6"]
    # the tail of the "all" view is still the reviewed rows (priority None), then no-end just above them
    allrows = snap.queue_rows(state="all")
    pend = allrows[allrows.priority.notna()]
    assert pend.iloc[-1].case_id == "noend:H6"


def test_queue_rows_filters(snapshot):
    assert set(snapshot.queue_rows(criterion="H6").criterion_id) == {"H6"}
    leg = snapshot.queue_rows(category="breached_legitimate")
    assert list(leg.case_id) == ["leg:H4"]
    assert set(snapshot.queue_rows(org="orgB").organization_id) == {"orgB"}
    assert list(snapshot.queue_rows(q="noend").case_id) == ["noend:H6"]


def test_queue_rows_reviewed_states(toy_processed, toy_protocol):
    h = toy_protocol.hash
    rows = [{"review_id": "a", "case_id": "sys:H4", "reviewer": "x", "validation_state": "validated",
             "human_status": "breached", "human_reason": "not_prescribed", "note": None, "pool": "estimation",
             "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": h},
            {"review_id": "b", "case_id": "leg:H4", "reviewer": "x", "validation_state": "flagged",
             "human_status": None, "human_reason": None, "note": "?", "pool": "estimation",
             "reviewed_ts": "2026-09-16T10:01:00", "protocol_hash": h}]
    with Store(toy_processed) as s:
        s.write_part("reviews", "r_a", review_frame(rows), h)
    snap = Snapshot.load(toy_processed, toy_protocol, now=NOW)
    assert "sys:H4" not in set(snap.queue_rows().case_id)
    v = snap.queue_rows(state="validated")
    assert list(v.case_id) == ["sys:H4"] and v.iloc[0].review_state == "validated" and v.iloc[0].category == "reviewed"
    assert snap.queue_rows(state="disputed").empty
    allrows = snap.queue_rows(state="all")
    assert len(allrows) == 21 and allrows.iloc[-1].review_state == "validated"  # reviewed rows sort last
    flagged = snap.queue_rows(state="flagged")
    assert flagged.case_id.tolist() == ["leg:H4"] and flagged.iloc[0].review_state == "flagged"
    pending = snap.queue_rows().set_index("case_id")
    assert "leg:H4" in pending.index and pending.loc["leg:H4"].review_state == "flagged"


def test_case_view(snapshot):
    c = snapshot.case("unv:H4")
    assert isinstance(c, CaseView) and c.criterion.id == "H4" and c.target_hours == 24
    assert c.status == "breached" and c.reason_tag == "not_prescribed" and c.reason_class == "system"
    assert len(c.evidence) == 1 and isinstance(c.evidence[0], Evidence)
    e = c.evidence[0]
    assert e.verified is False and e.bboxes == [] and e.page_id == "unv:ward_note:p1" and e.doc_type == "ward_note"
    assert c.computed_status_differs is False
    assert c.priority_reason and "evidence not verified on page" in c.priority_reason
    d = snapshot.case("dis:H4")
    assert d.computed_status_differs is True and d.evidence[0].bboxes == [{"x0": 0, "y0": 0, "x1": 1, "y1": 1}]
    n = snapshot.case("noend:H6")
    assert n.end_ts is None and n.category == "abstain_no_end"
    a = snapshot.case("abs:H2")
    assert a.start_ts is None and a.hours is None  # timing comes from the verdict's quoted times only
    assert d.hours == 40 and d.start_ts is not None
    with pytest.raises(KeyError):
        snapshot.case("nope:H4")


def test_case_view_review_history_newest_first(toy_processed, toy_protocol):
    h = toy_protocol.hash
    rows = [
        {"review_id": "a", "case_id": "sys:H4", "reviewer": "x", "validation_state": "validated",
         "human_status": "breached", "human_reason": "not_prescribed", "note": None, "pool": "estimation",
         "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": h},
        {"review_id": "b", "case_id": "sys:H4", "reviewer": "y", "validation_state": "disputed",
         "human_status": "not_breached", "human_reason": None, "note": "late", "pool": "estimation",
         "reviewed_ts": "2026-09-16T11:00:00", "protocol_hash": h},
    ]
    with Store(toy_processed) as s:
        s.write_part("reviews", "r_ab", review_frame(rows), h)
    c = Snapshot.load(toy_processed, toy_protocol, now=NOW).case("sys:H4")
    assert [r["review_id"] for r in c.reviews] == ["b", "a"]
    assert c.reviews[0]["note"] == "late" and c.category is None  # reviewed → not in the queue


def test_results_shape(snapshot):
    r = snapshot.results()
    assert {a["kind"] for a in r["alerts"]} >= {"top_time_lost"}
    assert all(a["action"] and a["owner"] and a["justification"] for a in r["alerts"])
    assert r["timelost"][0]["rank"] == 1
    assert all(t["rank"] is not None for t in r["timelost"])
    assert all(t["rank"] is None for t in r["timelost_orgs"])
    by_id = {c["criterion"].id: c for c in r["criteria"]}
    assert set(by_id) == {"H1", "H2", "H3", "H4", "H5", "H6"}
    h4 = by_id["H4"]
    assert h4["row"]["n"] == 14 and h4["provisional"] == "fewer than 2 reviews"
    assert isinstance(h4["reason_breakdown"], dict) and "not_prescribed" in h4["reason_breakdown"]
    assert by_id["H1"]["row"] is None or by_id["H1"]["row"]["n"] == 0  # no H1 cases in the toy data
    assert set(h4["funnel"].organization_id) == {"orgA", "orgB"}
