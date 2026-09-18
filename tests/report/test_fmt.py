from auditpace.report.fmt import ci, hours, pct, printed_tokens, printed_tokens_by_kind
from auditpace.report.gateway import validate_payload
from tests.report.conftest import minimal_payload


def test_formatters():
    assert pct(0.19326) == "19.3" and pct(None) == "—" and pct(float("nan")) == "—"
    assert ci(0.173783, 0.214353) == "17.4–21.4" and ci(None, 0.2) == "—"
    assert hours(6974.483) == "6974.5" and hours(None) == "—"


def test_printed_tokens_cover_every_figure_the_template_prints(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    toks = printed_tokens(p)
    for expected in ["28.6", "10.0", "50.0", "14", "3", "1", "0", "60.5", "8.0", "24", "H4", "Org-01", "Org-02",
                     "not_prescribed", "undetermined", "2020-W12", "2020-W11", "20", "2", "5", "0.8", "0.95",
                     "95", "95.0", "40-59", "2020", "6", "2020-01-01", "2020-12-31"]:
        assert expected in toks, expected
    assert "0.2857" not in toks  # raw floats are not printed


def test_printed_tokens_handles_no_period(vocab, toy_protocol):
    d = minimal_payload(toy_protocol)
    d["run"]["period"] = None
    p = validate_payload(d, vocab)
    toks = printed_tokens(p)
    for absent in ("2020-01-01", "2020-12-31", "2020"):
        assert absent not in toks
    for present in ("28.6", "H4"):
        assert present in toks


def test_printed_tokens_by_kind_classifies_each_figure(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    kinds = printed_tokens_by_kind(p)
    assert "28.6" in kinds["rate"] and "28.6" not in kinds["count"]
    assert "14" in kinds["count"]
    assert "60.5" in kinds["hours"]
    assert "H4" in kinds["id"] and "Org-02" in kinds["id"]
    assert "95" in kinds["rate"] and "95.0" in kinds["rate"]  # the 95 % CI level, not just "0.95"
    assert "40-59" in kinds["id"]  # a segment value, kept whole
    assert printed_tokens(p) == set().union(*kinds.values())
