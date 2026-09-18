from auditpace.report.compare import diff
from auditpace.report.gateway import validate_payload
from auditpace.report.prose import FALLBACK, FALLBACK_LENGTH, ProseRejection, empty_prose
from auditpace.report.render import HEADINGS, render_report
from tests.report.conftest import minimal_payload
from tests.report.test_compare import _payload
from tests.report.test_gateway import UUID_RE


def _render(toy_protocol, vocab, **kw):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    defaults = {"prose": empty_prose(["H4"], "PROSE"), "comparison": None, "note": "first run of this protocol",
                "rejections": [], "model_note": None}
    defaults.update(kw)
    return p, render_report(p, **defaults)


def test_headings_in_order_and_no_validation_without_coverage(toy_protocol, vocab):
    _p, md = _render(toy_protocol, vocab)
    found = [h for h in HEADINGS if f"\n## {h}" in md]
    assert found == [h for h in HEADINGS if not h.startswith("Validation")]
    assert md.startswith("# ") and "provisional" in md.split("\n", 3)[2].lower()


def test_figures_and_labels(toy_protocol, vocab):
    _p, md = _render(toy_protocol, vocab)
    assert "28.6 %" in md and "10.0–50.0 %" in md and "| H4 |" in md
    assert "fewer than 2 reviews" in md                       # provisional wording, verbatim
    assert "breached — stalled" in md and "breached — legitimate wait" in md   # category labels
    assert "suppressed (n < 5)" in md and "Org-01" in md and "Org-02" in md
    assert toy_protocol.action("H4", "not_prescribed") in md and toy_protocol.owner("H4") in md
    assert "Deprivation is not available in the source data" in md
    assert "PROSE" in md and md.count("PROSE") == 6          # summary + 3 + actions + caveats
    assert "urgency" not in md.lower() and "clinical priority" not in md.lower()
    assert not UUID_RE.search(md)
    assert "Cases with a review on file: 0 (validated 0, disputed 0, flagged 0)" in md


def test_caveats_seed_reviewer_and_rejections(toy_protocol, vocab):
    d = minimal_payload(toy_protocol)
    d["quality"]["reviews"]["reviewers"] = ["seed"]
    p = validate_payload(d, vocab)
    md = render_report(p, empty_prose(["H4"], FALLBACK), None, "", [], "report writer unavailable (HTTP 503)")
    assert "rehearsal seed" in md and "reviewer `seed`" in md
    assert "Narrative sections withheld: report writer unavailable (HTTP 503)" in md
    assert "every narrative paragraph is a placeholder" in md
    p2 = validate_payload(minimal_payload(toy_protocol), vocab)
    assert "rehearsal seed" not in render_report(p2, empty_prose(["H4"]), None, "", [], None)


def test_appendix_gateway_no_model_wording(toy_protocol, vocab):
    p, md = _render(toy_protocol, vocab)
    assert p.run.reporter.model is None
    assert "No report writer was used; every narrative paragraph is a placeholder." in md
    assert "paragraphs accepted" not in md


def test_appendix_gateway_model_unavailable_wording(toy_protocol, vocab):
    d = minimal_payload(toy_protocol)
    d["run"]["reporter"] = {"model": "google/medgemma-27b-text-it", "prompt_version": "rpt-000000000000"}
    p = validate_payload(d, vocab)
    md = render_report(p, empty_prose(["H4"]), None, "", [], "report writer unavailable (HTTP 503)")
    assert "Report writer unavailable (report writer unavailable (HTTP 503)); every narrative paragraph is a placeholder." in md
    assert "paragraphs accepted" not in md


def test_appendix_gateway_shows_withheld_count_when_model_ran(toy_protocol, vocab):
    d = minimal_payload(toy_protocol)
    d["run"]["reporter"] = {"model": "google/medgemma-27b-text-it", "prompt_version": "rpt-000000000000"}
    p = validate_payload(d, vocab)
    md = render_report(p, empty_prose(["H4"], FALLBACK), None, "",
                       [ProseRejection(section="summary", tokens=["23.4"], reason="token not in payload")], None)
    assert "1 paragraph" in md and "summary" in md   # appendix gateway summary names the rejected section
    assert "narrative paragraphs accepted" in md


def test_appendix_and_caveats_name_the_withheld_reason(toy_protocol, vocab):
    """Fix wave 2, item 2: the withheld-paragraph wording names the reason (`r.reason`) instead of
    always claiming "contained a figure not in the audited aggregates" — an over-length rejection
    (actions_note) must read as "over length", not as a fabricated-figure claim."""
    d = minimal_payload(toy_protocol)
    d["run"]["reporter"] = {"model": "google/medgemma-27b-text-it", "prompt_version": "rpt-000000000000"}
    p = validate_payload(d, vocab)
    prose = empty_prose(["H4"])
    prose.actions_note = FALLBACK_LENGTH
    rejections = [ProseRejection(section="actions_note", tokens=[], reason="over length")]
    md = render_report(p, prose, None, "", rejections, None)
    assert "actions_note (over length)" in md
    assert "narrative paragraphs accepted" in md


def test_comparison_section(toy_protocol, vocab):
    prev = _payload(toy_protocol, vocab, "rpt-20260917T100000-aaaaaaaa")
    cur = _payload(toy_protocol, vocab, "rpt-20260917T110000-bbbbbbbb", **{"criteria.0.corrected": {"rate": 0.2, "lo": 0.1, "hi": 0.3}})
    md = render_report(cur, empty_prose(["H4"]), diff(prev, cur), "", [], None)
    assert "rpt-20260917T100000-aaaaaaaa" in md and "−8.6" in md and "10.0–30.0 %" in md
    # A blank line must separate the comparison table from the "New alerts: ..." sentence, not run
    # the sentence into the table as an extra row (fix wave 2, item 1).
    assert "|\n\nNew alerts:" in md
    assert "re-assigned" not in md  # org_map_changed defaults to False
    md_reassigned = render_report(cur, empty_prose(["H4"]), diff(prev, cur, org_map_changed=True), "", [], None)
    assert "re-assigned" in md_reassigned
    md2 = render_report(cur, empty_prose(["H4"]), None, "previous run used a different protocol (abc); no comparison", [], None)
    assert "different protocol" in md2


def test_validation_section_names_h5_bias(toy_protocol, vocab):
    d = minimal_payload(toy_protocol)
    d["validation"] = {"present": True,
                       "coverage": [{"criterion_id": "H5", "fraction": 0.05, "method": "naive", "coverage": 0.0, "mean_width": 0.1},
                                    {"criterion_id": "H5", "fraction": 0.05, "method": "corrected", "coverage": 0.91, "mean_width": 0.2}],
                       "kappa": [{"criterion_id": "H5", "kappa": 0.42, "n": 219}],
                       "reason_accuracy": [{"criterion_id": "H5", "acc": 0.7, "n": 84}]}
    p = validate_payload(d, vocab)
    md = render_report(p, empty_prose(["H4"]), None, "", [], None)
    assert "## Validation on the synthetic cohort (not available on live data)" in md
    assert "hospital-admission-as-ICU-admission" in md and "| H5 | 0.42 | 219 |" in md


def test_missing_period_renders_without_error(toy_protocol, vocab):
    d = minimal_payload(toy_protocol)
    d["run"]["period"] = None
    p = validate_payload(d, vocab)
    md = render_report(p, empty_prose(["H4"]), None, "first run of this protocol", [], None)
    assert "period not set" in md
