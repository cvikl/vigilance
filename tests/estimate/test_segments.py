import json
import math

import pandas as pd
import pytest

from auditpace.estimate.categorise import categorise
from auditpace.estimate.reviews import empty_reviews, review_frame
from auditpace.estimate.segments import build_estimates
from tests.estimate.conftest import toy

NOW = pd.Timestamp("2026-09-16 12:00:00")


def _cf(protocol, rows, reviews=None):
    t = toy(rows, protocol)
    return categorise(t["verdicts"], t["cases"], t["patients"], reviews if reviews is not None else empty_reviews(), protocol)


def test_all_cell_counts_rates_and_suppression(locked_protocol):
    rows = [{"pid": f"p{i}", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 30, "org": "A"} for i in range(4)]
    rows += [{"pid": f"q{i}", "crit": "H4", "status": "breached", "reason": "contraindication_documented", "hours": 30, "org": "A"} for i in range(2)]
    rows += [{"pid": f"r{i}", "crit": "H4", "status": "not_breached", "hours": 3, "org": "B"} for i in range(4)]
    rows += [{"pid": "s0", "crit": "H4", "status": "abstain", "org": "B"}, {"pid": "s1", "crit": "H4", "status": "abstain", "end": False, "org": "B"}]
    est = build_estimates(_cf(locked_protocol, rows), locked_protocol, NOW)
    a = est[(est.criterion_id == "H4") & (est.segment_key == "all")].iloc[0]
    assert (a.n, a.n_abstain, a.n_no_end, a.n_reviewed) == (10, 1, 1, 0)
    assert (a.n_breached_system, a.n_breached_legitimate, a.n_breached_undetermined) == (4, 2, 0)
    assert a.naive_rate == 0.6 and a.corrected_rate == 0.6 and a.method == "naive" and a.flag == "n_reviewed_insufficient"
    assert a.rate_system == 0.4 and a.rate_legitimate == 0.2 and a.rate_undetermined == 0.0
    rb = json.loads(a.reason_breakdown)
    assert rb["not_prescribed"]["n"] == 4 and rb["contraindication_documented"]["rate"] == 0.2 and "undetermined" in rb
    assert set(rb) == set(next(c for c in locked_protocol.criteria if c.id == "H4").reasons) | {"undetermined"}
    orgs = est[(est.criterion_id == "H4") & (est.segment_key == "organization")].set_index("segment_value")
    assert orgs.loc["A", "n"] == 6 and orgs.loc["A", "naive_rate"] == 1.0 and not orgs.loc["A", "suppressed"]
    assert orgs.loc["B", "n"] == 4 and orgs.loc["B", "suppressed"] and math.isnan(orgs.loc["B", "naive_rate"])
    assert set(est.segment_key) == {"all", "age_band", "sex", "race", "ethnicity", "organization"}
    assert (est.computed_ts == NOW).all()


def test_reviews_move_corrected_but_not_naive(locked_protocol):
    rows = [{"pid": f"p{i}", "crit": "H5", "status": "breached", "reason": "decision_delayed", "hours": 30} for i in range(10)]
    h = locked_protocol.hash
    from auditpace.estimate.reviews import assign_pool
    est_ids = [f"p{i}:H5" for i in range(10) if assign_pool(f"p{i}:H5", h, 0.8) == "estimation"][:4]
    assert len(est_ids) >= 2
    reviews = review_frame([
        {"review_id": f"r{i}", "case_id": cid, "reviewer": "dr", "validation_state": "disputed", "human_status": "not_breached",
         "human_reason": None, "note": None, "pool": "estimation", "reviewed_ts": "2026-09-16T10:00:00", "protocol_hash": h}
        for i, cid in enumerate(est_ids)])
    est = build_estimates(_cf(locked_protocol, rows, reviews), locked_protocol, NOW)
    a = est[(est.criterion_id == "H5") & (est.segment_key == "all")].iloc[0]
    assert a.naive_rate == 1.0 and a.method == "ppi" and a.n_reviewed == len(est_ids)
    assert a.corrected_rate == 0.0 and a.corrected_lo == 0.0  # every reviewed breach overturned
    assert a.rate_system == 0.0  # indicator PPI moves with the reviews too


def test_unsupported_segment_key_raises(locked_protocol):
    rows = [{"pid": "p0", "crit": "H4", "status": "not_breached", "hours": 3}]
    bad = locked_protocol.model_copy(update={"segments": ["ward"]})
    with pytest.raises(ValueError, match="unsupported segments \\['ward'\\]"):
        build_estimates(_cf(locked_protocol, rows), bad, NOW)
