import json
import math
import re

import httpx
import pandas as pd
import pytest

from auditpace.adjudicate.stage import (
    RETRY_NOTE,
    AdjudicateStage,
    Batch,
    prompt_version,
    verdict_frame,
)
from auditpace.models import ModelJSONError

COLUMNS = {
    "case_id", "patient_id", "criterion_id", "status", "model_status", "reason_tag", "confidence",
    "from_ts", "to_ts", "hours_documented", "evidence", "rationale", "n_docs", "error", "model",
    "prompt_version", "read_version", "batch_id", "created_ts", "protocol_hash",
}


def _parse_prompt(messages):
    u = messages[-1]["content"]
    crit = re.match(r"Criterion (\S+) —", u).group(1)
    pid = re.search(r"### Document ([^:\n]+):", u).group(1)
    a = re.search(r"Event A \(from\): (\S+) —", u).group(1)
    b = re.search(r"Event B \(to\): (\S+) —", u).group(1)
    return crit, pid, a, b


class OracleClient:
    """Answers from documents.planted_facts (test-only): the case's own from/to time facts and, on
    a breached case, its reason fact with the true reason tag. Exercises verify+parse+compute."""

    def __init__(self, store):
        self.facts: dict[str, dict[str, tuple[str, str]]] = {}
        for d in store.read("documents").itertuples():
            for f in json.loads(d.planted_facts):
                key = f["kind"] + ":" + (f.get("event_type") or "")
                self.facts.setdefault(f["case_id"], {})[key] = (d.doc_id, f["text"])
        self.truth = store.read("cases").set_index("case_id")
        self.calls = 0

    def chat_json(self, messages, *, json_schema, temperature, max_tokens):
        self.calls += 1
        crit, pid, a, b = _parse_prompt(messages)
        f = self.facts.get(f"{pid}:{crit}", {})
        cite = lambda x: {"doc_id": x[0], "quote": x[1]} if x else None
        ft, tt, reason = f.get(f"time:{a}"), f.get(f"time:{b}"), f.get("reason:")
        tag = str(self.truth.at[f"{pid}:{crit}", "true_reason"]) if reason else None
        status = "breached" if reason else ("not_breached" if ft and tt else "abstain")
        return {"from_time": cite(ft), "to_time": cite(tt), "status": status, "reason_tag": tag,
                "evidence": [cite(reason)] if reason else [], "confidence": 0.9, "rationale": "oracle"}


class ScriptedClient:
    """Returns a fixed reply (or raises) for every call; records the messages it saw."""

    def __init__(self, reply=None, raises=(), n_raise=0):
        self.reply, self.raises, self.n_raise, self.seen = reply, raises, n_raise, []

    def chat_json(self, messages, *, json_schema, temperature, max_tokens):
        self.seen.append(messages)
        if len(self.seen) <= self.n_raise:
            raise self.raises[min(len(self.seen), len(self.raises)) - 1]
        return self.reply


def _stage(settings, protocol, store, client):
    return AdjudicateStage(settings, protocol, store, client=client)


def test_prompt_version_shape_and_inputs(monkeypatch):
    v = prompt_version("google/medgemma-27b-text-it", 1024)
    assert v.startswith("adj-") and len(v) == 16
    assert v != prompt_version("other", 1024) and v != prompt_version("google/medgemma-27b-text-it", 512)
    import auditpace.adjudicate.prompt as p
    monkeypatch.setattr(p, "SYSTEM_PROMPT", p.SYSTEM_PROMPT + " ")
    assert prompt_version("google/medgemma-27b-text-it", 1024) != v


def test_items_follow_readings_partitions(mini_settings, locked_protocol, mini_readings):
    assert list(_stage(mini_settings, locked_protocol, mini_readings, ScriptedClient()).items()) == [Batch("b0000")]


def test_oracle_run_recovers_structured_truth(mini_settings, locked_protocol, mini_readings):
    client = OracleClient(mini_readings)
    stage = _stage(mini_settings, locked_protocol, mini_readings, client)
    s = stage.run()
    assert (s.n_in, s.n_out, s.n_quarantined) == (1, 1, 0) and stage.n_errors == 0
    v = mini_readings.read("verdicts")
    cases = mini_readings.read("cases")
    want = cases[cases.applies]
    assert set(v.case_id) == set(want.case_id) and len(v) == len(want)
    assert set(v.columns) == COLUMNS
    assert (v.prompt_version == stage.version).all() and (v.protocol_hash == locked_protocol.hash).all()
    assert (v.model == mini_settings.models.adjudicator.model).all()
    m = v.merge(want, on="case_id", suffixes=("", "_t"))
    # split by "S2 planted time facts for this case", not end_ts: a post-death end (S1 artefact)
    # has end_ts but no facts, so no document can carry it and abstain is correct there too
    has_facts = m[m.case_id.isin(client.facts)]
    assert len(has_facts) >= 10, "mini cohort should have >= 10 documented cases"
    assert (has_facts.status != "abstain").all()
    assert ((has_facts.status == "breached") == has_facts.breached).all()
    assert ((has_facts.hours_documented - has_facts.hours).abs() <= 1 / 60 + 1e-9).all()
    assert (m[~m.case_id.isin(client.facts)].status == "abstain").all()
    br = m[m.status == "breached"]
    assert (br.reason_tag == br.true_reason).all()
    assert m[m.status != "breached"].reason_tag.isna().all()
    ev = [e for row in v.evidence for e in json.loads(row)]
    times = [e for e in ev if e["kind"] in ("from_time", "to_time")]
    assert sum(e["found"] for e in times) / len(times) >= 0.8
    assert all(bool(e["bboxes"]) == e["verified"] for e in ev)
    assert any(e["verified"] for e in ev)
    assert client.calls == len(want)


def test_resume_and_stale_prompt_version(mini_settings, locked_protocol, mini_readings, monkeypatch):
    client = OracleClient(mini_readings)
    stage = _stage(mini_settings, locked_protocol, mini_readings, client)
    stage.run()
    n = client.calls
    stage.run()
    assert client.calls == n, "second run must resume, not re-adjudicate"
    part = mini_readings.part_dir("verdicts") / "b0000.parquet"
    df = pd.read_parquet(part)
    df["prompt_version"] = "adj-000000000000"
    df.to_parquet(part, index=False)
    with pytest.raises(ValueError, match="stale"):
        stage.run()
    stage.run(force=True)
    assert (pd.read_parquet(part).prompt_version == stage.version).all()


def test_resume_and_stale_protocol_hash(mini_settings, locked_protocol, mini_readings):
    """A re-locked protocol that keeps the same applicable case_id set (e.g. a target_hours change)
    must not leave a verdicts partition looking current: _current also checks protocol_hash."""
    client = OracleClient(mini_readings)
    stage = _stage(mini_settings, locked_protocol, mini_readings, client)
    stage.run()
    part = mini_readings.part_dir("verdicts") / "b0000.parquet"
    df = pd.read_parquet(part)
    df["protocol_hash"] = "0" * 64
    df.to_parquet(part, index=False)
    with pytest.raises(ValueError, match="stale"):
        stage.run()
    stage.run(force=True)
    assert (pd.read_parquet(part).protocol_hash == stage.protocol.hash).all()


def test_computed_status_overrides_model_status(mini_settings, locked_protocol, mini_readings):
    """Model says breached but its own quoted times are within target → not_breached, reason null."""
    from auditpace.adjudicate.prompt import DocText
    from auditpace.adjudicate.stage import adjudicate_one
    c = next(c for c in locked_protocol.criteria if c.id == "H2")
    docs = [DocText("p:ed_clerking", "ed_clerking", pd.Timestamp("2020-03-11"), "SpO2 88% at 23:30 on 10/03/2020. Admitted 01:10 on 11/03/2020.")]
    reply = {"from_time": {"doc_id": "p:ed_clerking", "quote": "23:30 on 10/03/2020"},
             "to_time": {"doc_id": "p:ed_clerking", "quote": "01:10 on 11/03/2020"},
             "status": "breached", "reason_tag": "bed_unavailable", "evidence": [], "confidence": 0.7, "rationale": "r"}
    row = adjudicate_one(ScriptedClient(reply), c, "p:H2", "p", docs, {}, 1024)
    assert row["status"] == "not_breached" and row["model_status"] == "breached"
    assert row["reason_tag"] is None and abs(row["hours_documented"] - 1.6667) < 1e-3
    assert row["from_ts"] == pd.Timestamp("2020-03-10 23:30") and row["to_ts"] == pd.Timestamp("2020-03-11 01:10")
    ev = json.loads(row["evidence"])
    assert [e["kind"] for e in ev] == ["from_time", "to_time"] and all(e["found"] is False for e in ev)  # no pages given


def test_non_positive_gap_abstains(locked_protocol):
    """Identical from/to quotes (one sentence carrying both times) → abstain, hours_documented 0."""
    from auditpace.adjudicate.prompt import DocText
    from auditpace.adjudicate.stage import adjudicate_one
    c = next(c for c in locked_protocol.criteria if c.id == "H1")
    docs = [DocText("p:ed_clerking", "ed_clerking", pd.Timestamp("2020-03-05"), "text")]
    q = {"doc_id": "p:ed_clerking", "quote": "Swab taken at 17:12; result reported 18:46 on 05/03/2020."}
    reply = {"from_time": q, "to_time": q, "status": "not_breached", "reason_tag": "lab_backlog",
             "evidence": [], "confidence": 0.9, "rationale": "r"}
    row = adjudicate_one(ScriptedClient(reply), c, "p:H1", "p", docs, {}, 1024)
    assert row["status"] == "abstain" and row["model_status"] == "not_breached" and row["reason_tag"] is None
    assert row["hours_documented"] == 0 and row["from_ts"] == row["to_ts"] == pd.Timestamp("2020-03-05 18:46")
    reply["to_time"] = {"doc_id": "p:ed_clerking", "quote": "17:12 on 05/03/2020"}   # to before from
    row = adjudicate_one(ScriptedClient(reply), c, "p:H1", "p", docs, {}, 1024)
    assert row["status"] == "abstain" and row["hours_documented"] < 0


def test_missing_time_abstains_and_unknown_tag_dropped(mini_settings, locked_protocol):
    from auditpace.adjudicate.prompt import DocText
    from auditpace.adjudicate.stage import adjudicate_one
    c = next(c for c in locked_protocol.criteria if c.id == "H2")
    docs = [DocText("p:ed_clerking", "ed_clerking", pd.Timestamp("2020-03-11"), "text")]
    reply = {"from_time": {"doc_id": "p:ed_clerking", "quote": "23:30"}, "to_time": None, "status": "breached",
             "reason_tag": "bed_unavailable", "evidence": [], "confidence": 0.7, "rationale": "r"}
    row = adjudicate_one(ScriptedClient(reply), c, "p:H2", "p", docs, {}, 1024)
    assert row["status"] == "abstain" and row["model_status"] == "breached" and row["reason_tag"] is None
    assert pd.isna(row["from_ts"]) and math.isnan(row["hours_documented"]) and row["error"] is None
    reply2 = {**reply, "to_time": {"doc_id": "p:ed_clerking", "quote": "09:00 on 12/03/2020"},
              "from_time": {"doc_id": "p:ed_clerking", "quote": "23:30 on 10/03/2020"}, "reason_tag": "not_in_taxonomy"}
    row = adjudicate_one(ScriptedClient(reply2), c, "p:H2", "p", docs, {}, 1024)
    assert row["status"] == "breached" and row["reason_tag"] is None


def test_no_documents_abstains_without_a_call(locked_protocol):
    from auditpace.adjudicate.stage import adjudicate_one
    c = locked_protocol.criteria[0]
    client = ScriptedClient()
    row = adjudicate_one(client, c, "p:H1", "p", [], {}, 1024)
    assert row["status"] == "abstain" and row["n_docs"] == 0 and row["model_status"] is None and client.seen == []


def test_bad_json_retries_with_note_then_abstains_with_error(locked_protocol):
    from auditpace.adjudicate.prompt import DocText
    from auditpace.adjudicate.stage import adjudicate_one
    c = locked_protocol.criteria[0]
    docs = [DocText("p:lab_report", "lab_report", pd.Timestamp("2020-03-11"), "text")]
    client = ScriptedClient(raises=(ModelJSONError("bad"),), n_raise=2)
    row = adjudicate_one(client, c, "p:H1", "p", docs, {}, 1024)
    assert len(client.seen) == 2
    assert client.seen[1][-1]["content"].endswith(RETRY_NOTE) and not client.seen[0][-1]["content"].endswith(RETRY_NOTE)
    assert row["status"] == "abstain" and row["error"].startswith("ModelJSONError")
    client = ScriptedClient(reply={"status": "nope"}, raises=(), n_raise=0)
    row = adjudicate_one(client, c, "p:H1", "p", docs, {}, 1024)
    assert row["error"].startswith("ValidationError") and len(client.seen) == 2


def test_transport_error_quarantines_batch(mini_settings, locked_protocol, mini_readings):
    client = ScriptedClient(raises=(httpx.ConnectError("down"),), n_raise=99)
    stage = _stage(mini_settings, locked_protocol, mini_readings, client)
    s = stage.run()
    assert s.n_quarantined == 1 and not mini_readings.exists("verdicts")
    assert len(client.seen) == 2, "one retry, then re-raise"


def test_null_string_columns_stay_readable_across_partitions(mini_settings, locked_protocol, mini_readings):
    """A partition whose reason_tag/error are all null must be typed string, not arrow `null`, or
    DuckDB's glob view over verdicts/*.parquet cannot read a later partition that has strings."""
    abstain = {"from_time": None, "to_time": None, "status": "abstain", "reason_tag": None,
               "evidence": [], "confidence": 0.5, "rationale": "r"}
    stage = _stage(mini_settings, locked_protocol, mini_readings, ScriptedClient(abstain))
    assert stage.run().n_quarantined == 0            # b0000: reason_tag and error all null
    b0 = pd.read_parquet(mini_readings.part_dir("verdicts") / "b0000.parquet")
    assert b0.reason_tag.isna().all() and b0.error.isna().all()
    first = b0.iloc[0].to_dict()
    rows = [{**first, "case_id": "x:H1", "patient_id": "x", "status": "breached", "model_status": "breached",
             "reason_tag": "other", "error": None},
            {**first, "case_id": "x:H2", "patient_id": "x", "status": "abstain", "model_status": None,
             "reason_tag": None, "error": "ModelJSONError: bad"}]
    mini_readings.write_part("verdicts", "b0001", verdict_frame(rows), locked_protocol.hash)
    q = mini_readings.sql(
        "select typeof(error) te, typeof(reason_tag) tr, typeof(model_status) tm, count(*) n, "
        "count(error) n_err, count(reason_tag) n_reason, count(model_status) n_ms from verdicts "
        "group by all"
    ).iloc[0]
    assert (q.te, q.tr, q.tm) == ("VARCHAR", "VARCHAR", "VARCHAR")
    assert (q.n, q.n_err, q.n_reason, q.n_ms) == (len(b0) + 2, 1, 1, len(b0) + 1)
    bad = mini_readings.sql(
        "select count(*) from verdicts where error = 'None' or reason_tag = 'None' or model_status = 'None'"
    ).iloc[0, 0]
    assert bad == 0
    v = mini_readings.read("verdicts")
    assert v.reason_tag.dropna().tolist() == ["other"] and v.error.dropna().tolist() == ["ModelJSONError: bad"]
