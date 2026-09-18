import json
import re

import pandas as pd
import pytest

from auditpace.synth.facts import Fact
from auditpace.synth.plan import DocSpec
from auditpace.synth.prompt import OUTPUT_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt

UUID = "0001049f-9248-47fe-b479-ea80eb51ce4a"


def _spec(pid=UUID, doc_type="ed_clerking"):
    ts = pd.Timestamp("2020-03-12 15:40")
    return DocSpec(f"{pid}:{doc_type}", pid, doc_type, ts, "handwritten",
                   (("hypoxaemia", pd.Timestamp("2020-03-12 10:15")), ("admitted", pd.Timestamp("2020-03-12 14:20"))),
                   (Fact(f"{pid}:H2:time:hypoxaemia", f"{pid}:H2", "time", "10:15 on 12/03/2020", "hypoxaemia"),
                    Fact(f"{pid}:H2:time:admitted", f"{pid}:H2", "time", "14:20 on 12/03/2020", "admitted"),
                    Fact(f"{pid}:H4:time:admitted", f"{pid}:H4", "time", "14:20 on 12/03/2020", "admitted"),
                    Fact(f"{pid}:H2:reason", f"{pid}:H2", "reason", "No medical bed available; patient boarded in ED awaiting ward allocation.")),
                   None)


def test_user_prompt_aliases_and_dedups_must_include():
    pat = pd.Series({"patient_id": UUID, "age_band": "60-79", "sex": "F"})
    prompt, planned = build_user_prompt([(pat, [_spec()])])
    assert UUID not in prompt
    data = json.loads(prompt)
    p = data["patients"][0]
    assert p["alias"] == "P1" and p["age_band"] == "60-79" and p["sex"] == "F" and p["died"] is None
    d = p["documents"][0]
    assert d["doc_id"] == "P1:ed_clerking" and d["doc_type"] == "ed_clerking" and d["authored_ts"] == "2020-03-12T15:40"
    assert d["known_events"] == [{"event": "hypoxaemia", "label": "hypoxaemia recorded (SpO2 below 92% on air)", "when": "10:15 on 12/03/2020"},
                                 {"event": "admitted", "label": "admitted to hospital", "when": "14:20 on 12/03/2020"}]
    assert d["must_include"] == ["10:15 on 12/03/2020", "14:20 on 12/03/2020",
                                 "No medical bed available; patient boarded in ED awaiting ward allocation."]
    assert "style" not in d  # rendering concern, not the author's
    assert planned == {"P1:ed_clerking": _spec()}


def test_two_patients_get_distinct_aliases():
    a = pd.Series({"patient_id": "a", "age_band": "18-39", "sex": "M"})
    b = pd.Series({"patient_id": "b", "age_band": "80+", "sex": "F"})
    prompt, planned = build_user_prompt([(a, [_spec("a", "lab_report")]), (b, [_spec("b", "lab_report")])])
    assert set(planned) == {"P1:lab_report", "P2:lab_report"}
    assert [p["alias"] for p in json.loads(prompt)["patients"]] == ["P1", "P2"]


def test_schema_and_version():
    assert OUTPUT_SCHEMA["additionalProperties"] is False
    assert OUTPUT_SCHEMA["properties"]["documents"]["items"]["required"] == ["doc_id", "text"]
    assert re.fullmatch(r"synth-[0-9a-f]{12}", PROMPT_VERSION)
    for term in ("NEWS2", "verbatim", "JSON", "known_events", "must_include", "died"):
        assert term in SYSTEM_PROMPT


def test_duplicate_doc_type_raises():
    pat = pd.Series({"patient_id": UUID, "age_band": "60-79", "sex": "F"})
    spec1 = _spec(UUID, "ed_clerking")
    spec2 = _spec(UUID, "ed_clerking")
    with pytest.raises(ValueError, match="duplicate document"):
        build_user_prompt([(pat, [spec1, spec2])])
