from pathlib import Path

import pandas as pd
import pytest

from auditpace.protocol import Criterion, load_protocol
from auditpace.synth.facts import (
    DISTRACTORS,
    REASONS,
    Fact,
    check_bank,
    distractor_fact,
    reason_fact,
    time_fact,
    time_text,
)

P = load_protocol(Path(__file__).resolve().parents[2] / "protocol.yaml")


def test_bank_covers_every_protocol_reason_with_three_variants():
    check_bank(P.criteria)
    for c in P.criteria:
        for r in c.reasons:
            assert len(REASONS[c.id][r]) >= 3
        assert len(DISTRACTORS[c.id]) >= 3


def test_every_phrase_is_a_sentence():
    phrases = [t for d in REASONS.values() for v in d.values() for t in v] + [t for v in DISTRACTORS.values() for t in v]
    assert all(t == t.strip() and t[0].isupper() and t.endswith(".") and len(t.split()) >= 5 for t in phrases)
    assert len(phrases) == len(set(phrases))


def test_check_bank_raises_on_missing_code():
    bad = Criterion(id="H1", name="x", type="handoff", **{"from": "suspected"}, to="confirmed", target_hours=1,
                    standard="s", reasons=["swab_delay", "unknown_code", "other"])
    with pytest.raises(ValueError, match="H1.*unknown_code"):
        check_bank([bad])


def test_time_text_and_time_fact():
    ts = pd.Timestamp("2020-03-12 14:20:33.123456")
    assert time_text(ts) == "14:20 on 12/03/2020"
    f = time_fact("p1:H2", "admitted", ts)
    assert f == Fact("p1:H2:time:admitted", "p1:H2", "time", "14:20 on 12/03/2020", "admitted")
    assert f.to_dict()["event_type"] == "admitted"


def test_reason_and_distractor_seeded_and_from_bank():
    a = reason_fact("p1:H2", "H2", "bed_unavailable", seed=42)
    b = reason_fact("p1:H2", "H2", "bed_unavailable", seed=42)
    assert a == b and a.kind == "reason" and a.text in REASONS["H2"]["bed_unavailable"]
    assert a.fact_id == "p1:H2:reason" and a.event_type is None
    picks = {reason_fact(f"p{i}:H2", "H2", "bed_unavailable", seed=42).text for i in range(40)}
    assert len(picks) >= 2  # different cases draw different variants
    d = distractor_fact("p1:H4", "H4", seed=42)
    assert d.kind == "distractor" and d.fact_id == "p1:H4:distractor" and d.text in DISTRACTORS["H4"]
