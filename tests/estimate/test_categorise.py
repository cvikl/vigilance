import pandas as pd

from auditpace.estimate.categorise import CATEGORIES, categorise
from auditpace.estimate.reviews import empty_reviews, review_frame
from tests.estimate.conftest import toy


def _rev(case_id, state, status, reason, pool, ts, h):
    return {"review_id": f"r-{case_id}-{ts}", "case_id": case_id, "reviewer": "dr", "validation_state": state,
            "human_status": status, "human_reason": reason, "note": None, "pool": pool,
            "reviewed_ts": ts, "protocol_hash": h}


def test_categories_from_verdicts_only(locked_protocol):
    t = toy([
        {"pid": "a", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 30},
        {"pid": "b", "crit": "H4", "status": "breached", "reason": "contraindication_documented", "hours": 40},
        {"pid": "c", "crit": "H4", "status": "breached", "reason": None, "hours": 50},
        {"pid": "d", "crit": "H4", "status": "not_breached", "hours": 5},
        {"pid": "e", "crit": "H4", "status": "abstain"},
        {"pid": "f", "crit": "H6", "status": "not_breached", "end": False, "hours": 3},   # died-in-hospital pattern
        {"pid": "g", "crit": "H6", "status": "abstain", "end": False},
    ], locked_protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], empty_reviews(), locked_protocol)
    got = dict(zip(cf.case_id, cf.category))
    assert got == {"a:H4": "breached_system", "b:H4": "breached_legitimate", "c:H4": "breached_undetermined",
                   "d:H4": "not_breached", "e:H4": "abstain", "f:H6": "abstain_no_end", "g:H6": "abstain_no_end"}
    assert set(cf.category) <= set(CATEGORIES)
    r = cf.set_index("case_id")
    assert r.loc["a:H4", "excess_hours"] == 6 and r.loc["d:H4", "excess_hours"] == 0
    assert pd.isna(r.loc["e:H4", "hours"]) and pd.isna(r.loc["f:H6", "hours"])
    assert bool(r.loc["a:H4", "yhat"]) and not bool(r.loc["d:H4", "yhat"]) and not bool(r.loc["e:H4", "yhat"])
    assert list(cf.estimable) == [True, True, True, True, False, False, False]
    assert cf.y.isna().all() and not cf.reviewed.any()
    assert (cf.organization == "orgA").all() and cf.week.iloc[0] == "2020-W10"
    assert r.loc["c:H4", "reason_class"] == "undetermined" and pd.isna(r.loc["d:H4", "reason_class"])


def test_reviews_override_status_and_class_but_never_no_end(locked_protocol):
    t = toy([
        {"pid": "a", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 30},
        {"pid": "b", "crit": "H4", "status": "not_breached", "hours": 5},
        {"pid": "c", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 30},
        {"pid": "f", "crit": "H6", "status": "not_breached", "end": False, "hours": 3},
        {"pid": "h", "crit": "H4", "status": "abstain"},  # end present, verdict abstain
        {"pid": "j", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 30},  # called verdict, reviewer abstains
    ], locked_protocol)
    h = locked_protocol.hash
    reviews = review_frame([
        _rev("a:H4", "disputed", "breached", "contraindication_documented", "estimation", "2026-09-16T10:00:00", h),
        _rev("b:H4", "disputed", "breached", None, "tuning", "2026-09-16T10:00:00", h),
        _rev("c:H4", "flagged", None, None, "estimation", "2026-09-16T10:00:00", h),
        _rev("f:H6", "disputed", "breached", "not_booked", "estimation", "2026-09-16T10:00:00", h),
        _rev("a:H4", "validated", "breached", "not_prescribed", "estimation", "2026-09-16T09:00:00", h),  # older, loses
        _rev("h:H4", "disputed", "breached", "not_prescribed", "estimation", "2026-09-16T10:00:00", h),
        _rev("j:H4", "disputed", "abstain", None, "estimation", "2026-09-16T10:00:00", h),
    ])
    cf = categorise(t["verdicts"], t["cases"], t["patients"], reviews, locked_protocol).set_index("case_id")
    assert cf.loc["a:H4", "category"] == "breached_legitimate" and cf.loc["a:H4", "y"] is True
    assert cf.loc["b:H4", "category"] == "breached_undetermined" and cf.loc["b:H4", "y"] is None  # tuning pool: no Y
    assert cf.loc["b:H4", "reviewed"] and cf.loc["b:H4", "pool"] == "tuning"
    assert cf.loc["c:H4", "category"] == "breached_system" and not cf.loc["c:H4", "reviewed"]
    assert cf.loc["c:H4", "review_state"] == "flagged" and cf.loc["c:H4", "y"] is None
    assert cf.loc["f:H6", "category"] == "abstain_no_end" and cf.loc["f:H6", "y"] is None and not cf.loc["f:H6", "estimable"]
    assert cf.loc["f:H6", "reviewed"]  # ruling 2: reviewed decoupled from the no-end override
    assert bool(cf.loc["a:H4", "yhat"])  # yhat stays the verdict's call
    # ruling 1: a verdict-abstain case (end present) reviewed as breached stays "abstain" — never overridden
    assert cf.loc["h:H4", "category"] == "abstain" and not cf.loc["h:H4", "estimable"]
    assert not bool(cf.loc["h:H4", "yhat"]) and cf.loc["h:H4", "y"] is None
    assert cf.loc["h:H4", "effective_status"] == "abstain" and pd.isna(cf.loc["h:H4", "reason_class"])
    assert cf.loc["h:H4", "review_state"] in ("validated", "disputed") and cf.loc["h:H4", "pool"] == "estimation"
    assert cf.loc["h:H4", "reviewed"]  # ruling 2: a non-flagged review exists, regardless of override
    # ruling 1 (regression fix): a reviewer setting human_status="abstain" on a called verdict also
    # categorises "abstain", not "not_breached" — even though the verdict itself said breached
    assert cf.loc["j:H4", "category"] == "abstain" and not cf.loc["j:H4", "estimable"]
    assert not bool(cf.loc["j:H4", "yhat"]) and cf.loc["j:H4", "y"] is None
    assert pd.isna(cf.loc["j:H4", "hours"])
    assert cf.loc["j:H4", "reviewed"]


def test_status_less_review_never_overrides(locked_protocol):
    """Belt and braces for rubric C1: `review_frame` refuses a non-flagged review without a status, but a
    hand-built frame that slips one through must still leave the verdict's category untouched."""
    t = toy([{"pid": "a", "crit": "H4", "status": "breached", "reason": "not_prescribed", "hours": 30}], locked_protocol)
    h = locked_protocol.hash
    reviews = review_frame([_rev("a:H4", "flagged", None, None, "estimation", "2026-09-16T10:00:00", h)])
    reviews["validation_state"] = "validated"  # bypasses review_frame's check on purpose
    cf = categorise(t["verdicts"], t["cases"], t["patients"], reviews, locked_protocol).set_index("case_id")
    assert cf.loc["a:H4", "category"] == "breached_system" and cf.loc["a:H4", "effective_status"] == "breached"
    assert cf.loc["a:H4", "reviewed"] and cf.loc["a:H4", "y"] is None


def test_unverified_evidence_and_unknown_org(locked_protocol):
    t = toy([{"pid": "a", "crit": "H1", "status": "breached", "reason": "swab_delay", "hours": 30, "verified": False, "org": None}],
            locked_protocol)
    cf = categorise(t["verdicts"], t["cases"], t["patients"], empty_reviews(), locked_protocol)
    assert bool(cf.any_unverified.iloc[0]) and cf.organization.iloc[0] == "unknown"
