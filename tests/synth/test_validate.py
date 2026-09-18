import pandas as pd

from auditpace.synth.facts import Fact
from auditpace.synth.plan import DocSpec
from auditpace.synth.validate import BANLIST, fact_needle, validate_batch

WORDS = " ".join(["word"] * 80)


def _planned():
    ts = pd.Timestamp("2020-03-12 15:40")
    f1 = Fact("p:H2:time:admitted", "p:H2", "time", "14:20 on 12/03/2020", "admitted")
    f2 = Fact("p:H2:reason", "p:H2", "reason", "No medical bed available; patient boarded in ED awaiting ward allocation.")
    return {"P1:ed_clerking": DocSpec("p:ed_clerking", "p", "ed_clerking", ts, "typed", (), (f1, f2), None),
            "P1:lab_report": DocSpec("p:lab_report", "p", "lab_report", ts, "typed", (), (), None)}


def _ok():
    return {"documents": [
        {"doc_id": "P1:ed_clerking", "text": f"Admitted at 14:20 on 12/03/2020. No medical bed available; patient boarded in ED awaiting ward allocation. {WORDS}"},
        {"doc_id": "P1:lab_report", "text": f"SARS-CoV-2 PCR positive. {WORDS}"},
    ]}


def test_clean_batch_passes():
    assert validate_batch(_planned(), _ok()) == []


def test_missing_extra_and_duplicate_doc_ids():
    r = _ok()
    r["documents"][1]["doc_id"] = "P1:ward_round"
    errs = validate_batch(_planned(), r)
    assert any("missing" in e and "P1:lab_report" in e for e in errs)
    assert any("unexpected" in e and "P1:ward_round" in e for e in errs)
    r = _ok()
    r["documents"].append(dict(r["documents"][0]))
    assert any("duplicate" in e and "P1:ed_clerking" in e for e in validate_batch(_planned(), r))


def test_fact_must_be_verbatim():
    r = _ok()
    r["documents"][0]["text"] = r["documents"][0]["text"].replace("14:20 on 12/03/2020", "14.20 on 12/3/2020")
    errs = validate_batch(_planned(), r)
    assert len(errs) == 1 and "P1:ed_clerking" in errs[0] and "p:H2:time:admitted" in errs[0] and "14:20 on 12/03/2020" in errs[0]


def test_banlist_and_length():
    r = _ok()
    r["documents"][1]["text"] = "Seen in the ER by the attending physician. " + WORDS
    errs = validate_batch(_planned(), r)
    assert any("P1:lab_report" in e and "ER" in e and "attending physician" in e for e in errs)
    r = _ok()
    r["documents"][1]["text"] = "Too short."
    assert any("P1:lab_report" in e and "words" in e for e in validate_batch(_planned(), r))
    r = _ok()
    r["documents"][1]["text"] = " ".join(["long"] * 601)
    assert any("words" in e for e in validate_batch(_planned(), r))
    assert BANLIST.search("acetaminophen given") and not BANLIST.search("paracetamol given")
    assert not BANLIST.search("INTERNAL medicine") and not BANLIST.search("emergency department")
    assert not BANLIST.search("nurse attending to the patient")


def test_fact_terminal_punctuation_may_be_continued():
    r = _ok()
    r["documents"][0]["text"] = r["documents"][0]["text"].replace(
        "No medical bed available; patient boarded in ED awaiting ward allocation.",
        "No medical bed available; patient boarded in ED awaiting ward allocation, so the family were updated.",
    )
    assert validate_batch(_planned(), r) == []
    r = _ok()
    r["documents"][0]["text"] = r["documents"][0]["text"].replace(
        "No medical bed available; patient boarded in ED awaiting ward allocation.",
        "No medical bed available; patient boarded in the ED awaiting ward allocation.",
    )
    errs = validate_batch(_planned(), r)
    assert len(errs) == 1 and "P1:ed_clerking" in errs[0] and "p:H2:reason" in errs[0]


def test_malformed_return_reports_not_raises():
    assert validate_batch(_planned(), {}) and validate_batch(_planned(), {"documents": [{"doc_id": "P1:lab_report"}]})


def test_fact_needle_strips_only_terminal_punctuation():
    assert fact_needle("Seen at 10:15 on 12/03/2020.") == "Seen at 10:15 on 12/03/2020"
    assert fact_needle("No bed available!?") == "No bed available"
    assert fact_needle("10:15 on 12/03/2020") == "10:15 on 12/03/2020"
