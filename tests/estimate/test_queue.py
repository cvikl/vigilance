import pandas as pd

from auditpace.estimate.alerts import build_alerts
from auditpace.estimate.categorise import categorise
from auditpace.estimate.funnel import build_funnel
from auditpace.estimate.queue import WEIGHTS, build_queue
from auditpace.estimate.reviews import empty_reviews, review_frame
from auditpace.estimate.runchart import build_runchart
from auditpace.estimate.segments import build_estimates
from auditpace.estimate.timelost import build_timelost
from tests.estimate.conftest import toy

NOW = pd.Timestamp("2026-09-16 12:00:00")


def _queue(protocol, rows, reviews=None):
    t = toy(rows, protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], reviews if reviews is not None else empty_reviews(), protocol)
    est = build_estimates(cf, protocol, NOW)
    fun = build_funnel(cf, est, protocol, NOW)
    rc = build_runchart(cf, est, protocol, NOW)
    al = build_alerts(cf, est, fun, rc, build_timelost(cf, NOW), protocol, NOW)
    return cf, al, build_queue(cf, al, NOW)


def test_ordering_reasons_and_no_end(locked_protocol):
    base = [{"pid": f"z{i}", "crit": "H4", "status": "not_breached", "hours": 4, "org": "A"} for i in range(6)]
    rows = base + [
        {"pid": "dis", "crit": "H4", "status": "breached", "model_status": "not_breached", "reason": "not_prescribed", "hours": 26, "org": "A"},
        {"pid": "unv", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 26, "org": "A", "verified": False},
        {"pid": "abs", "crit": "H4", "status": "abstain", "org": "A"},
        {"pid": "big", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 48, "org": "A"},
        {"pid": "noe", "crit": "H6", "status": "abstain", "end": False, "org": "A"},
    ]
    _, _, q = _queue(locked_protocol, rows)
    q = q.set_index("case_id")
    # all H4 rows get ci_leverage (no reviews yet) and in_alerted_segment only if an alert matched their cell
    assert q.loc["dis:H4", "priority"] >= WEIGHTS["model_disagrees"] + WEIGHTS["ci_leverage"]
    assert "model call ≠ computed status" in q.loc["dis:H4", "priority_reason"]
    assert "evidence not verified on page" in q.loc["unv:H4", "priority_reason"]
    assert "abstained though end event exists" in q.loc["abs:H4", "priority_reason"]
    assert q.loc["big:H4", "excess_hours"] == 24 and "24.0 h over target" in q.loc["big:H4", "priority_reason"]
    assert q.loc["noe:H6", "priority"] == 0 and q.loc["noe:H6", "priority_reason"] == "no follow-up documented — nothing to review"
    order = list(q.sort_values(["priority", "case_id"], ascending=[False, True]).index)
    assert list(q.index) == order and order[0] == "dis:H4"


def test_reviewed_rows_drop_and_flagged_stay(locked_protocol):
    rows = [{"pid": f"p{i}", "crit": "H1", "status": "breached", "reason": "swab_delay", "hours": 30} for i in range(3)]
    h = locked_protocol.hash
    reviews = review_frame([
        {"review_id": "r1", "case_id": "p0:H1", "reviewer": "dr", "validation_state": "validated", "human_status": "breached",
         "human_reason": "swab_delay", "note": None, "pool": "estimation", "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": h},
        {"review_id": "r2", "case_id": "p1:H1", "reviewer": "dr", "validation_state": "flagged", "human_status": None,
         "human_reason": None, "note": "?", "pool": "estimation", "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": h},
    ])
    _, _, q = _queue(locked_protocol, rows, reviews)
    assert set(q.case_id) == {"p1:H1", "p2:H1"}


def test_alerted_segment_flag(locked_protocol):
    rows = [{"pid": f"a{i}", "crit": "H2", "status": "breached" if i < 9 else "not_breached", "reason": "bed_unavailable", "hours": 10, "org": "bad"} for i in range(10)]
    rows += [{"pid": f"b{i}", "crit": "H2", "status": "breached" if i < 2 else "not_breached", "reason": "bed_unavailable", "hours": 10, "org": "ok"} for i in range(40)]
    _, al, q = _queue(locked_protocol, rows)
    assert (al.kind == "org_outlier").any()
    q = q.set_index("case_id")
    assert "in alerted cell: org_outlier:H2:bad" in q.loc["a0:H2", "priority_reason"]
    assert "org_outlier:H2:bad" not in q.loc["b0:H2", "priority_reason"]
