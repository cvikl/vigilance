import hashlib
import json
from pathlib import Path

import pytest

from auditpace.report.gateway import GatewayLog, GatewayViolation
from auditpace.report.prose import FALLBACK, UNAVAILABLE
from auditpace.report.stage import ReportStage
from auditpace.store import Store
from tests.report.conftest import NOW
from tests.report.test_prose import FakeReporter, _reply


def _stage(toy_store, toy_protocol, mini_settings, tmp_path, **kw):
    store = Store(toy_store)
    out = kw.pop("out", tmp_path / "docs" / "report.md")
    return store, ReportStage(mini_settings, toy_protocol, store, model=kw.pop("model", None),
                              compare_to=kw.pop("compare_to", None), out=out, now=kw.pop("now", NOW), **kw)


def test_no_model_run_writes_everything(toy_store, toy_protocol, mini_settings, tmp_path):
    store, st = _stage(toy_store, toy_protocol, mini_settings, tmp_path)
    with store:
        summary = st.process("report")
    run_dir = Path(toy_store) / "report" / summary["run_id"]
    assert (run_dir / "payload.json").exists() and (run_dir / "prose.json").exists() and (run_dir / "report.md").exists()
    assert (run_dir / "org_map.json").exists() and (run_dir / "gateway.log").exists()
    assert (Path(toy_store) / "report" / "gateway.log").exists()
    md = (tmp_path / "docs" / "report.md").read_text()
    assert md == (run_dir / "report.md").read_text() and UNAVAILABLE in md and toy_protocol.question in md
    lines = GatewayLog.lines(run_dir / "gateway.log")
    assert [x["status"] for x in lines] == ["sent", "payload"] and lines[0]["model"] is None
    payload_bytes = (run_dir / "payload.json").read_bytes()
    assert lines[0]["sha256"] == hashlib.sha256(payload_bytes).hexdigest()
    assert lines[0]["n_bytes"] == len(payload_bytes)
    assert lines[0]["sha256"][:12] in (run_dir / "report.md").read_text()
    assert summary["sent"] == 1 and summary["rejected"] == 0 and summary["prose_rejected"] == 0
    org_map = json.loads((run_dir / "org_map.json").read_text())
    assert set(org_map) == {"Org-01", "Org-02"}


def test_reporter_prose_is_checked_and_logged(toy_store, toy_protocol, mini_settings, tmp_path):
    cids = ["H2", "H4", "H6"]
    reply = _reply(cids, "Reviewed 0 cases.")
    reply["criteria"]["H4"]["where"] = "H4 breached in 99.9 % of cases."
    store, st = _stage(toy_store, toy_protocol, mini_settings, tmp_path, model="medgemma", reporter=FakeReporter([reply]))
    with store:
        summary = st.process("report")
    run_dir = Path(toy_store) / "report" / summary["run_id"]
    prose = json.loads((run_dir / "prose.json").read_text())
    assert prose["prose"]["criteria"]["H4"]["where"] == FALLBACK and prose["rejections"][0]["section"] == "criteria.H4.where"
    statuses = [x["status"] for x in GatewayLog.lines(run_dir / "gateway.log")]
    assert statuses == ["sent", "payload", "prose_rejected"]
    assert summary["prose_rejected"] == 1 and "99.9" not in (run_dir / "report.md").read_text()


def test_model_unavailable_falls_back(toy_store, toy_protocol, mini_settings, tmp_path):
    """The raw error text ("boom again") is un-back-checked model output: it must not reach the
    rendered report, only the class-level reason. The full text still lands in the gateway-log
    `model_unavailable` line and prose.json's `model_note_detail` — the audit trail keeps it,
    the report does not print it (fix wave 2, item 3)."""
    from auditpace.models import ModelJSONError
    store, st = _stage(toy_store, toy_protocol, mini_settings, tmp_path, model="medgemma",
                       reporter=FakeReporter([ModelJSONError("boom"), ModelJSONError("boom again")]))
    with store:
        summary = st.process("report")
    md = (tmp_path / "docs" / "report.md").read_text()
    assert "Narrative sections withheld: report writer unavailable" in md
    assert "boom again" not in md
    assert summary["model_unavailable"] == 1
    run_dir = Path(toy_store) / "report" / summary["run_id"]
    lines = GatewayLog.lines(run_dir / "gateway.log")
    statuses = [x["status"] for x in lines]
    assert statuses == ["sent", "payload", "model_unavailable"]
    assert "boom again" in lines[-1]["error"]
    prose_json = json.loads((run_dir / "prose.json").read_text())
    assert "boom again" in prose_json["model_note_detail"]


def test_second_run_compares_to_first(toy_store, toy_protocol, mini_settings, tmp_path):
    store, st = _stage(toy_store, toy_protocol, mini_settings, tmp_path)
    with store:
        first = st.process("report")
    import pandas as pd
    store2, st2 = _stage(toy_store, toy_protocol, mini_settings, tmp_path, now=NOW + pd.Timedelta(hours=1))
    with store2:
        second = st2.process("report")
    assert second["run_id"] != first["run_id"]
    md = (tmp_path / "docs" / "report.md").read_text()
    assert f"Previous run `{first['run_id']}`" in md
    assert "re-assigned" not in md  # same cohort, same org_map: not org_map_changed


def test_org_map_changed_when_pseudonyms_reassigned(toy_store, toy_protocol, mini_settings, tmp_path):
    """spec §7: `org_map_changed` compares the previous run's org_map.json to the current one; a
    different mapping (Org-nn pseudonyms swapped) must surface in the "Change since previous run"
    section, not silently mislead the reader into comparing Org-nn labels across runs."""
    store, st = _stage(toy_store, toy_protocol, mini_settings, tmp_path)
    with store:
        first = st.process("report")
    org_map_path = Path(toy_store) / "report" / first["run_id"] / "org_map.json"
    org_map = json.loads(org_map_path.read_text())
    keys = list(org_map)
    assert len(keys) >= 2, org_map
    org_map[keys[0]], org_map[keys[1]] = org_map[keys[1]], org_map[keys[0]]
    org_map_path.write_text(json.dumps(org_map, indent=1, sort_keys=True), encoding="utf-8")
    import pandas as pd
    store2, st2 = _stage(toy_store, toy_protocol, mini_settings, tmp_path, now=NOW + pd.Timedelta(hours=1))
    with store2:
        st2.process("report")
    md = (tmp_path / "docs" / "report.md").read_text()
    assert "re-assigned" in md


def test_gateway_violation_propagates(toy_store, toy_protocol, mini_settings, tmp_path):
    with Store(toy_store) as s:
        al = s.read("alerts")
        al.loc[0, "owner"] = "Dr 1f6e17d1-4c15-4397-9c4f-753e89c1d114"
        s.write("alerts", al, toy_protocol.hash)
    store, st = _stage(toy_store, toy_protocol, mini_settings, tmp_path)
    with store, pytest.raises(GatewayViolation):
        st.run()   # Stage.run must not quarantine it
    lines = GatewayLog.lines(Path(toy_store) / "report" / "gateway.log")
    assert lines[-1]["status"] == "rejected" and "alerts[0].owner" in lines[-1]["field"]
