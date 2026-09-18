import json
import re

import httpx
import pytest

from auditpace.models import ModelJSONError
from auditpace.report.gateway import validate_payload
from auditpace.report.prose import (
    FALLBACK,
    FALLBACK_LENGTH,
    UNAVAILABLE,
    Prose,
    ProseUnavailable,
    VLLMReporter,
    ask_model,
    check_prose,
    empty_prose,
    prompt_version,
    prose_schema,
    system_prompt,
    user_message,
)
from tests.report.conftest import minimal_payload


class FakeReporter:
    """A `Reporter` stand-in: replies come off a queue, exceptions raise instead of returning."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def reply(self, system, user, schema):
        self.calls.append((system, user, schema))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _reply(cids, text="ok"):
    return {"summary": text, "criteria": {c: {"where": text, "why": text, "who": text} for c in cids},
            "actions_note": text, "caveats_note": text}


def _good_prose():
    return Prose(summary="H4 admission to VTE prophylaxis breached in 28.6 % of 14 cases "
                         "(interval 10.0–50.0 %). The interval is provisional: fewer than 2 reviews.",
                 criteria={"H4": {"where": "Time is lost in 28.6 % of cases against a 24 h target.",
                                  "why": "not_prescribed dominates; one case was a legitimate wait.",
                                  "who": "Org-02 sits above its funnel limit (50.0 %, n = 6)."}},
                 actions_note="Actions rest with the ward pharmacist / trust VTE lead.",
                 caveats_note="Every interval is provisional with fewer than 2 reviews.")


def test_schema_keys_follow_protocol(vocab, toy_protocol):
    s = prose_schema(["H2", "H4"])
    assert set(s["properties"]["criteria"]["properties"]) == {"H2", "H4"}
    assert s["properties"]["criteria"]["additionalProperties"] is False
    assert s["additionalProperties"] is False


def test_prompt_version_changes_with_prompt(monkeypatch):
    v1 = prompt_version("google/medgemma-27b-text-it", 2048)
    assert re.fullmatch(r"rpt-[0-9a-f]{12}", v1)
    import auditpace.report.prose as P
    monkeypatch.setattr(P, "SYSTEM_PROMPT", P.SYSTEM_PROMPT + " x")
    assert prompt_version("google/medgemma-27b-text-it", 2048) != v1
    assert "never" in system_prompt().lower() and "patient" in system_prompt().lower()


def test_check_prose_accepts_prose_made_of_payload_tokens(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    prose, rejections = check_prose(_good_prose(), p, vocab)
    assert rejections == [] and prose.criteria["H4"].who.startswith("Org-02")


def test_check_prose_rejects_invented_figure(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    bad = _good_prose()
    bad.criteria["H4"].where = "Time is lost in 23.4 % of cases."
    prose, rejections = check_prose(bad, p, vocab)
    assert prose.criteria["H4"].where == FALLBACK
    assert [r.section for r in rejections] == ["criteria.H4.where"] and "23.4" in rejections[0].tokens
    assert prose.summary != FALLBACK  # other paragraphs untouched


def test_check_prose_rejects_ids_and_unknown_criterion(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    bad = _good_prose()
    bad.summary = "Patient 1f6e17d1-4c15-4397-9c4f-753e89c1d114 breached."
    bad.actions_note = "H7 needs attention."
    bad.caveats_note = "Org-09 was an outlier."
    prose, rejections = check_prose(bad, p, vocab)
    assert prose.summary == FALLBACK and prose.actions_note == FALLBACK and prose.caveats_note == FALLBACK
    assert {r.section for r in rejections} == {"summary", "actions_note", "caveats_note"}


def test_check_prose_small_integers_and_thousands_separators(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    ok = _good_prose()
    ok.summary = "Three of six criteria were reviewed; 2 are provisional; n = 14 cases; 1,454 is not here."
    prose, rejections = check_prose(ok, p, vocab)
    assert prose.summary == FALLBACK and "1454" in rejections[0].tokens
    ok.summary = "Three of six criteria were reviewed; 2 are provisional; n = 14 cases."
    prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []
    ok.summary = "Breaches ran at 12 %."   # bare small int with a % suffix is a rounded rate → rejected
    prose, rejections = check_prose(ok, p, vocab)
    assert prose.summary == FALLBACK


def test_check_prose_rejects_over_length(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    long = _good_prose()
    long.actions_note = " ".join(["word"] * 100)  # limit 80, +20 % = 96
    prose, rejections = check_prose(long, p, vocab)
    assert prose.actions_note == FALLBACK_LENGTH and rejections[0].reason == "over length"


def test_empty_prose():
    e = empty_prose(["H2", "H4"])
    assert e.summary == UNAVAILABLE and set(e.criteria) == {"H2", "H4"} and e.criteria["H2"].why == UNAVAILABLE


def test_check_prose_rejects_spelled_out_numbers(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    bad = _good_prose()
    bad.summary = "Breaches ran at twenty-nine per cent of cases."
    prose, rejections = check_prose(bad, p, vocab)
    assert prose.summary == FALLBACK and "twenty-nine" in rejections[0].tokens

    ok = _good_prose()
    ok.summary = "Two of three criteria are provisional."
    prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []

    bad2 = _good_prose()
    bad2.summary = "Hundreds of cases were reviewed."
    prose, rejections = check_prose(bad2, p, vocab)
    assert prose.summary == FALLBACK and "hundreds" in [t.lower() for t in rejections[0].tokens]


def test_check_prose_accepts_the_95_per_cent_confidence_level(vocab, toy_protocol):
    """The recorded 27B reply wrote "95 per cent confidence interval"; 0.95 only ever printed as
    "0.95" in the payload proper — the 95 %/95.0 forms are the template's own "95 % CI" wording."""
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    ok = _good_prose()
    ok.summary = "The 95 per cent confidence interval is 10.0–50.0 %."
    _prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []


def test_check_prose_keeps_a_segment_value_whole(vocab, toy_protocol):
    """A segment value like "40-59" is one allowed id token; NUM_RE must not be let split it into
    the two bare numbers "40" and "59"."""
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    ok = _good_prose()
    ok.summary = "Breaches ran in the 40-59 age band (28.6 %) and for Org-02 (50.0 %)."
    prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []

    bad = _good_prose()
    bad.summary = "Breaches ran in the 40-59 age band and 41 % overall."
    prose, rejections = check_prose(bad, p, vocab)
    assert prose.summary == FALLBACK and "41" in rejections[0].tokens


def test_check_prose_compound_tokens_are_matched_whole_not_by_substring(vocab, toy_protocol):
    """A fabricated number that merely CONTAINS an allowed compound id token (a segment band, an ISO
    week, an ISO date) must not ride through on that substring: the compound scan only recognises a
    bounded token (digit/dot on neither side), so "140-591" and "20200" are still caught even though
    they contain "40-59" and "2020"."""
    p = validate_payload(minimal_payload(toy_protocol), vocab)

    accepted = [
        "Breaches ran at 28.6 % in the 40-59 age band.",
        "The period ran from 2020-01-01 to 2020-12-31.",
        "Week 2020-W12 showed 30.0 %.",
    ]
    for text in accepted:
        ok = _good_prose()
        ok.summary = text
        _prose, rejections = check_prose(ok, p, vocab)
        assert rejections == [], text

    ok = _good_prose()
    ok.summary = "This sits against the interval 10.0-50.0 %."
    _prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []

    cases = [
        ("Total of 20200 cases were seen this period.", "20200"),
        ("Breaches ran in the 140-591 band overall.", "140-591"),
        ("The audit period ran from 2020-01-05 to 2020-12-31.", "2020-01-05"),
        ("Breaches were worse in the 60-79 age band.", "60-79"),  # shaped like a band, not in payload
    ]
    for text, token in cases:
        bad = _good_prose()
        bad.summary = text
        _prose, rejections = check_prose(bad, p, vocab)
        assert _prose.summary == FALLBACK and token in rejections[0].tokens, (text, rejections)

    ident = _good_prose()
    ident.summary = "Patient 1f6e17d1-4c15-4397-9c4f-753e89c1d114 breached."
    _prose, rejections = check_prose(ident, p, vocab)
    assert _prose.summary == FALLBACK and "identifier" in rejections[0].tokens


def test_check_prose_checks_suffix_against_the_right_kind(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)

    bad = _good_prose()
    bad.summary = "Breaches ran at 14 percent of cases."  # 14 is a count (n), not a rate
    prose, rejections = check_prose(bad, p, vocab)
    assert prose.summary == FALLBACK and "14" in rejections[0].tokens

    ok = _good_prose()
    ok.summary = "Breaches ran at 28.6 % of cases in 14 cases."
    prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []

    ok.summary = "The target 24 h holds."
    prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []

    ok.summary = "This sits against the 24-hour target."
    prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []

    bad2 = _good_prose()
    bad2.summary = "This took 60.5 % of the time."  # 60.5 is hours_lost, not a rate
    prose, rejections = check_prose(bad2, p, vocab)
    assert prose.summary == FALLBACK and "60.5" in rejections[0].tokens


def test_user_message_is_stable_json(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    msg = user_message(p)
    assert msg == json.dumps(p.for_model(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert "run_id" not in msg and p.run.protocol_hash in msg
    assert "\n " not in msg  # compact: no indentation whitespace to burn tokens on


def test_ask_model_returns_prose(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    rep = FakeReporter([_reply(["H4"], "fine")])
    prose = ask_model(rep, p, ["H4"])
    assert prose.criteria["H4"].where == "fine"
    _system, user, schema = rep.calls[0]
    assert "run_id" not in user and p.run.protocol_hash in user  # for_model() payload
    assert schema["properties"]["criteria"]["required"] == ["H4"]


def test_ask_model_retries_once_then_raises(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    rep = FakeReporter([ModelJSONError("bad"), _reply(["H4"])])
    assert ask_model(rep, p, ["H4"]).summary == "ok" and len(rep.calls) == 2
    rep = FakeReporter([ModelJSONError("bad"), {"summary": "missing the rest"}])
    with pytest.raises(ProseUnavailable):
        ask_model(rep, p, ["H4"])


def test_ask_model_raises_on_criterion_mismatch(vocab, toy_protocol):
    """A reply that parses as Prose but for the wrong criterion set must not be returned as-is."""
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    rep = FakeReporter([_reply(["H4", "H5"]), _reply(["H4", "H5"])])
    with pytest.raises(ProseUnavailable):
        ask_model(rep, p, ["H4"])
    assert len(rep.calls) == 2


def test_vllm_reporter_length_is_an_error(monkeypatch):
    class C:
        def chat_full(self, messages, **kw):
            return '{"summary": "trunc', "length"

    with pytest.raises(Exception, match="length"):
        VLLMReporter(C()).reply("s", "u", {"type": "object"})

    class OK:
        def chat_full(self, messages, **kw):
            assert messages[0]["role"] == "system" and kw["json_schema"]["type"] == "object"
            return '{"a": 1}', "stop"

    assert VLLMReporter(OK()).reply("s", "u", {"type": "object"}) == {"a": 1}


def test_vllm_reporter_non_json_is_a_model_json_error():
    class C:
        def chat_full(self, messages, **kw):
            return "not json", "stop"

    with pytest.raises(ModelJSONError):
        VLLMReporter(C()).reply("s", "u", {"type": "object"})


def test_vllm_reporter_wraps_httpx_errors():
    """A network failure from ModelClient._call must not escape raw: ask_model's retry loop only
    catches (ModelJSONError, ValueError), so VLLMReporter.reply wraps httpx errors itself."""

    class C:
        def chat_full(self, messages, **kw):
            raise httpx.HTTPError("boom")

    with pytest.raises(ModelJSONError, match="boom"):
        VLLMReporter(C()).reply("s", "u", {"type": "object"})


def test_check_prose_rejects_proportions_from_exempt_small_integers(vocab, toy_protocol):
    """"1 in 3 cases", "nine in ten", "one out of four" — both sides may be small integers exempt
    from the numeric scan on their own, but the "in"/"out of" proportion phrasing is rejected
    outright (fix wave 2, item 4)."""
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    for text in ["1 in 3 cases breached.", "Nine in ten were reviewed.", "About one out of four cases were affected."]:
        bad = _good_prose()
        bad.summary = text
        prose, rejections = check_prose(bad, p, vocab)
        assert prose.summary == FALLBACK, text

    ok = _good_prose()
    ok.summary = "Two of three criteria are provisional."  # "of", not "in"/"out of" — still accepted
    prose, rejections = check_prose(ok, p, vocab)
    assert rejections == []


def test_check_prose_rejects_case_insensitive_ids_and_extra_number_words(vocab, toy_protocol):
    """Fix wave 2, item 7: CRIT_RE/ORG_RE/ID_RE are case-insensitive, and NUMBER_WORD_EXTRA_RE
    catches "dozen"/"tenth"/etc without touching NUMBER_WORD_RE.pattern (the prompt_version blob)."""
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    for text in ["ORG-99 was an outlier.", "h7 needs attention.", "About a dozen cases were affected.",
                "A tenth of cases breached."]:
        bad = _good_prose()
        bad.summary = text
        prose, _rejections = check_prose(bad, p, vocab)
        assert prose.summary == FALLBACK, text
