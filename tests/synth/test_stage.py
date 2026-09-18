import json

import pandas as pd
import pytest
from typer.testing import CliRunner

from auditpace.cli import app
from auditpace.synth.prompt import PROMPT_VERSION
from auditpace.synth.stage import Batch, SynthStage
from tests.synth.conftest import EchoClient, FlakyClient


def test_items_are_sorted_batches(mini_settings, locked_protocol, mini_store):
    s = SynthStage(mini_settings, locked_protocol, mini_store, client=EchoClient(), batch_size=2)
    items = list(s.items())
    assert [b.batch_id for b in items] == ["b0000", "b0001", "b0002"]
    ids = [pid for b in items for pid in b.patient_ids]
    assert ids == sorted(mini_store.read("patients").patient_id) and len(items[-1].patient_ids) == 1
    assert isinstance(items[0], Batch)


def test_process_writes_partition_and_is_done(mini_settings, locked_protocol, mini_store):
    client = EchoClient()
    s = SynthStage(mini_settings, locked_protocol, mini_store, client=client)
    summary = s.run()
    assert (summary.n_in, summary.n_out, summary.n_quarantined) == (1, 1, 0) and len(client.calls) == 1
    docs = mini_store.read("documents")
    assert set(docs.columns) == {"doc_id", "patient_id", "doc_type", "authored_ts", "style", "text", "planted_facts",
                                 "batch_id", "model", "prompt_version", "protocol_hash"}
    assert (docs.batch_id == "b0000").all() and (docs.prompt_version == PROMPT_VERSION).all()
    assert (docs.model == "sonnet").all() and set(docs.protocol_hash) == {locked_protocol.hash}
    assert str(docs.authored_ts.dtype) == "datetime64[us]"
    assert not docs.doc_id.str.startswith("P").any() and docs.patient_id.str.len().eq(36).all()
    assert 15 <= len(docs) <= 30 and docs.doc_type.isin(["lab_report", "ed_clerking", "ward_round", "icu_note",
                                                          "discharge_summary", "clinic_letter"]).all()
    facts = [f for pf in docs.planted_facts for f in json.loads(pf)]
    assert all({"fact_id", "case_id", "kind", "text", "event_type"} == set(f) for f in facts)
    cases = mini_store.read("cases").merge(mini_store.read("patients")[["patient_id", "deathdate"]], on="patient_id")
    documentable = cases.deathdate.isna() | (cases.end_ts <= cases.deathdate.dt.normalize() + pd.Timedelta(hours=23, minutes=59))
    breached = set(cases[cases.applies & cases.breached & documentable].case_id)
    assert {f["case_id"] for f in facts if f["kind"] == "reason"} == breached
    for f in facts:
        doc = docs[docs.doc_id == next(d.doc_id for d in docs.itertuples() if f in json.loads(d.planted_facts))].iloc[0]
        assert f["text"] in doc.text
    # second run: nothing to do; force re-authors
    s2 = SynthStage(mini_settings, locked_protocol, mini_store, client=client)
    assert s2.run().n_out == 1 and len(client.calls) == 1
    assert s2.run(force=True).n_out == 1 and len(client.calls) == 2


def test_retry_then_success_and_quarantine_after_three(mini_settings, locked_protocol, mini_store):
    client = EchoClient(fail_first=1)
    s = SynthStage(mini_settings, locked_protocol, mini_store, client=client)
    assert s.run().n_quarantined == 0 and len(client.calls) == 2
    assert "Previous attempt rejected" in client.calls[1] and "not verbatim" in client.calls[1]
    client = EchoClient(fail_first=3)
    s = SynthStage(mini_settings, locked_protocol, mini_store, client=client)
    summary = s.run(force=True)
    assert summary.n_quarantined == 1 and len(client.calls) == 3
    q = json.loads((mini_store.dir / "quarantine" / "synth.jsonl").read_text().strip())
    assert "b0000" in q["item"] and "not verbatim" in q["error"]


def test_workers_equal_sequential(mini_settings, locked_protocol, mini_store):
    a = SynthStage(mini_settings, locked_protocol, mini_store, client=EchoClient(), batch_size=2)
    a.run(force=True)
    seq = mini_store.read("documents").sort_values("doc_id").reset_index(drop=True)
    b = SynthStage(mini_settings, locked_protocol, mini_store, client=EchoClient(), batch_size=2)
    assert b.run(force=True, workers=3).n_out == 3
    par = mini_store.read("documents").sort_values("doc_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(seq, par)


def test_cli_exit_codes(mini_settings, locked_protocol, mini_store, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    proto = tmp_path / "protocol.yaml"
    monkeypatch.setattr("auditpace.cmd_synth.SynthStage",
                        lambda s, p, st, **kw: SynthStage(s, p, st, client=EchoClient(raise_always=True), **kw))
    r = CliRunner().invoke(app, ["synth", "--protocol", str(proto)])
    assert r.exit_code == 1 and "quarantined" in r.output
    monkeypatch.setattr("auditpace.cmd_synth.SynthStage",
                        lambda s, p, st, **kw: SynthStage(s, p, st, client=EchoClient(), **kw))
    r = CliRunner().invoke(app, ["synth", "--protocol", str(proto), "--workers", "1", "--batch-size", "5"])
    assert r.exit_code == 0 and "synth: in=1 out=1 quarantined=0" in r.output


def test_cli_requires_cohort(mini_settings, locked_protocol, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    r = CliRunner().invoke(app, ["synth", "--protocol", str(tmp_path / "protocol.yaml")])
    assert r.exit_code == 2 and "auditpace cohort" in r.output


def test_batch_size_change_raises_without_force(mini_settings, locked_protocol, mini_store):
    s5 = SynthStage(mini_settings, locked_protocol, mini_store, client=EchoClient(), batch_size=5)
    s5.run()
    s2 = SynthStage(mini_settings, locked_protocol, mini_store, client=EchoClient(), batch_size=2)
    with pytest.raises(ValueError, match="not produced by batch_size"):
        s2.run()


def test_batch_size_change_force_replaces_stale_partitions(mini_settings, locked_protocol, mini_store):
    s5 = SynthStage(mini_settings, locked_protocol, mini_store, client=EchoClient(), batch_size=5)
    s5.run()
    s2 = SynthStage(mini_settings, locked_protocol, mini_store, client=EchoClient(), batch_size=2)
    summary = s2.run(force=True)
    assert summary.n_out == 3
    stems = sorted(p.stem for p in mini_store.part_dir("documents").glob("*.parquet"))
    assert stems == ["b0000", "b0001", "b0002"]
    assert mini_store.read("documents").doc_id.is_unique


def test_cli_batch_size_change_requires_force(mini_settings, locked_protocol, mini_store, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    proto = tmp_path / "protocol.yaml"
    monkeypatch.setattr("auditpace.cmd_synth.SynthStage",
                        lambda s, p, st, **kw: SynthStage(s, p, st, client=EchoClient(), **kw))
    r = CliRunner().invoke(app, ["synth", "--protocol", str(proto), "--batch-size", "5"])
    assert r.exit_code == 0
    r2 = CliRunner().invoke(app, ["synth", "--protocol", str(proto), "--batch-size", "2"])
    assert r2.exit_code == 2 and "--force" in r2.output


def test_transport_error_retries_with_original_prompt(mini_settings, locked_protocol, mini_store):
    client = FlakyClient(fail_first=1)
    s = SynthStage(mini_settings, locked_protocol, mini_store, client=client)
    summary = s.run()
    assert summary.n_quarantined == 0 and len(client.calls) == 2
    assert client.calls[0] == client.calls[1]  # transport failure: retried with the ORIGINAL prompt


def test_transport_error_always_fails_quarantines(mini_settings, locked_protocol, mini_store):
    client = FlakyClient(always_fail=True)
    s = SynthStage(mini_settings, locked_protocol, mini_store, client=client)
    summary = s.run()
    assert summary.n_quarantined == 1 and len(client.calls) == 3
    q = json.loads((mini_store.dir / "quarantine" / "synth.jsonl").read_text().strip())
    assert "model call failed" in q["error"]
