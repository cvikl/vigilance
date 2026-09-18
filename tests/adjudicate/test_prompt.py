import json
import re

import pandas as pd
import pytest
from pydantic import ValidationError

from auditpace.adjudicate.prompt import (
    EVENT_GLOSS,
    REASON_GLOSS,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    DocText,
    Reply,
    build_messages,
    reply_schema,
)


def _crit(locked_protocol, cid="H2"):
    return next(c for c in locked_protocol.criteria if c.id == cid)


def test_gloss_covers_every_protocol_event(locked_protocol):
    assert set(EVENT_GLOSS) >= set(locked_protocol.events)
    assert all(g for g in EVENT_GLOSS.values())


def _tokens(text: str) -> list[str]:
    """Lower-cased words, punctuation stripped; a reason-code identifier (underscores kept) is one
    token, so `lost_to_follow_up` — a protocol name the model must see — is not itself a 4-gram."""
    return re.sub(r"[^a-z0-9_ ]+", " ", text.lower()).split()


def _ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    t = _tokens(text)
    return {tuple(t[i:i + n]) for i in range(len(t) - n + 1)}


def test_reason_gloss_covers_protocol(locked_protocol):
    for c in locked_protocol.criteria:
        for r in c.reasons:
            assert REASON_GLOSS[c.id][r] and REASON_GLOSS[c.id][r] != r, (c.id, r)


def test_prompt_shares_no_four_token_run_with_planted_phrases(locked_protocol):
    """R11: no planted (reasons.yaml) or distractor phrasing may enter the adjudication prompt —
    no run of 4 tokens (lower-cased, punctuation stripped) shared between any prompt string (the
    constants and every criterion's rendered system/user message) and any planted phrase."""
    from pathlib import Path

    import yaml

    import auditpace.synth
    root = Path(auditpace.synth.__file__).parent
    planted = yaml.safe_load((root / "reasons.yaml").read_text())
    phrases = [ph for crit in planted.values() for variants in crit.values() for ph in variants]
    distractors = yaml.safe_load((root / "distractors.yaml").read_text())
    phrases += [ph for variants in distractors.values() for ph in variants]
    planted_grams = {g for ph in phrases for g in _ngrams(ph)}
    prompt_strings = [*(g for d in REASON_GLOSS.values() for g in d.values()), *EVENT_GLOSS.values(),
                      SYSTEM_PROMPT, USER_TEMPLATE]
    for c in locked_protocol.criteria:   # rendered messages: code-name/gloss and line boundaries
        prompt_strings += [m["content"] for m in build_messages(c, [])]
    leaks = {" ".join(g) for s in prompt_strings for g in _ngrams(s) & planted_grams}
    assert not leaks, sorted(leaks)


def test_schema_enums_follow_criterion(locked_protocol):
    c = _crit(locked_protocol)
    s = reply_schema(c)
    assert s["properties"]["status"]["enum"] == ["breached", "not_breached", "abstain"]
    assert s["properties"]["reason_tag"]["enum"] == [*c.reasons, None]
    assert s["required"] == ["from_time", "to_time", "rationale", "status", "reason_tag", "evidence", "confidence"]
    assert list(s["properties"]) == s["required"]   # generation order: rationale before status
    assert s["additionalProperties"] is False
    assert s["properties"]["evidence"]["maxItems"] == 3
    json.dumps(s)  # serialisable


def test_build_messages_orders_docs_and_states_criterion(locked_protocol):
    c = _crit(locked_protocol)
    docs = [
        DocText("p:ward_round", "ward_round", pd.Timestamp("2020-03-12 09:00"), "later doc"),
        DocText("p:ed_clerking", "ed_clerking", pd.Timestamp("2020-03-11 01:30"), "page one\n\npage two"),
    ]
    msgs = build_messages(c, docs)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == SYSTEM_PROMPT
    u = msgs[1]["content"]
    assert u.startswith("Criterion H2 — Hypoxaemia to admission\n")
    assert "Event A (from): hypoxaemia — " + EVENT_GLOSS["hypoxaemia"] in u
    assert "Event B (to): admitted — " + EVENT_GLOSS["admitted"] in u
    assert "Target: B within 4 hours of A" in u
    assert "Standard: NICE NG191 / BTS oxygen guideline" in u
    assert "Reason codes:\n- bed_unavailable: there was nowhere on a ward to put the patient\n- referral_not_received: " in u
    assert "\n- other: a cause not listed above\n" in u
    assert u.index("### Document p:ed_clerking (ed_clerking, authored 01:30 on 11/03/2020)") \
        < u.index("### Document p:ward_round (ward_round, authored 09:00 on 12/03/2020)")
    assert "page one\n\npage two" in u


def test_system_prompt_demands_full_time_string_and_verbatim_quotes():
    assert "14:20 on 12/03/2020" in SYSTEM_PROMPT
    assert "character-for-character" in SYSTEM_PROMPT
    assert "letterhead" in SYSTEM_PROMPT


def test_reply_validates():
    r = Reply.model_validate({"from_time": {"doc_id": "d", "quote": "q"}, "to_time": None, "status": "abstain",
                              "reason_tag": None, "evidence": [], "confidence": 0.5, "rationale": "x"})
    assert r.from_time.doc_id == "d" and r.to_time is None
    with pytest.raises(ValidationError):
        Reply.model_validate({"status": "maybe"})
