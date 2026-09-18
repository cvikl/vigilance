import math

from auditpace.workbench.render import (
    category_label,
    ci,
    demo_href,
    hours,
    make_env,
    pct,
    provisional_reason,
)


def test_provisional_rule_all_branches():
    assert provisional_reason(25, None) is None
    assert provisional_reason(10, None) == "fewer than 20 reviews"
    assert provisional_reason(30, "no_discrepancy_observed").startswith("no review has yet disagreed")
    assert provisional_reason(1, "n_reviewed_insufficient") == "fewer than 2 reviews"
    assert provisional_reason(0, float("nan")) == "fewer than 20 reviews"  # NaN flag from parquet


def test_category_labels():
    assert category_label("abstain_no_end", "H6") == "no follow-up documented"
    assert category_label("abstain_no_end", "H4") == "no end event documented"
    assert category_label("abstain", "H2") == "abstained (end event exists)"
    assert category_label("breached_system", "H4") == "breached — stalled"
    assert category_label("breached_legitimate", "H4") == "breached — legitimate wait"
    assert category_label("breached_undetermined", "H4") == "breached — reason undetermined"
    assert category_label("not_breached", "H4") == "not breached"
    assert category_label("reviewed", "H4") == "reviewed"


def test_number_filters():
    assert pct(0.3536) == "35.4 %"
    assert pct(None) == "—" and pct(math.nan) == "—"
    assert ci(0.329, 0.379) == "32.9–37.9 %"
    assert ci(math.nan, 0.5) == "—"
    assert hours(41.26) == "41.3 h" and hours(math.nan) == "—"


def test_demo_href():
    assert demo_href("/queue", False) == "/queue"
    assert demo_href("/queue", True) == "/queue?demo=1"
    assert demo_href("/queue?criterion=H4", True) == "/queue?criterion=H4&demo=1"


def test_env_has_filters_and_autoescape():
    env = make_env()
    t = env.from_string("{{ x|pct }} {{ '<b>'|e }} {{ p|demo_href(true) }}")
    assert t.render(x=0.5, p="/case/a") == "50.0 % &lt;b&gt; /case/a?demo=1"
    assert env.autoescape


def test_queue_table_reason_cell_fallbacks():
    """A pending row with no fired flag (priority_reason == "") must not print "reviewed: None"; a reviewed
    row (not in the `queue` table, so priority_reason is None) prints its review state."""
    env = make_env()
    base = {"case_id": "x:H1", "patient_id": "x", "criterion_id": "H1", "priority": 0.0, "category": "not_breached",
            "status": "not_breached", "model_status": "not_breached", "reason_tag": None, "hours": 1.0,
            "target_hours": 24.0, "first_quote": "q", "any_unverified": False, "age_band": "18-39", "sex": "F"}
    rows = [dict(base, priority_reason="", review_state=None),
            dict(base, case_id="y:H1", priority_reason=None, review_state="validated", category="reviewed")]
    html = env.get_template("partials/queue_table.html").render(rows=rows, n_no_end=0, demo=False)
    assert "reviewed: None" not in html
    assert "no flags fired — check in any order" in html
    assert "reviewed: validated" in html


def test_why_flags_reads_as_plain_language():
    from auditpace.workbench.render import why_flags
    raw = ("model call ≠ computed status; evidence not verified on page; abstained though end event exists; "
           "in alerted cell: criterion_below_target:H4:all; 24.0 h over target; few reviews yet for H4")
    texts = [f["text"] for f in why_flags(raw)]
    assert texts == ["model and computed status disagree", "quote not on page", "abstained despite end event",
                     "H4 below target, service-wide", "24.0 h over target", "few reviews yet on H4"]
    assert why_flags("in alerted cell: org_outlier:H2:ac83")[0]["text"] == "organisation is an outlier on H2"
    assert why_flags("no follow-up documented — nothing to review")[0]["kind"] == "note"
    assert why_flags("") == [] and why_flags(None) == []
