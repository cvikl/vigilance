"""Replays the recorded MedGemma 27B prose for the toy payload (record with AUDITPACE_RECORD=1 and
`ONLY=27b make serve` up). Asserts the contract, not the wording: valid Prose, every criterion, and
whatever the back-check rejected is logged rather than printed."""
import json
from pathlib import Path

from auditpace.report.gateway import GatewayLog
from auditpace.report.prose import FALLBACK, UNAVAILABLE
from auditpace.report.stage import ReportStage
from auditpace.store import Store
from tests.report.conftest import NOW

RUN_ID = "rpt-20260917T120000-00000000"


def test_replay_27b_prose(toy_store, toy_protocol, mini_settings, tmp_path, monkeypatch):
    import auditpace.report.stage as S
    monkeypatch.setattr(S, "code_sha", lambda: "0000000")
    out = tmp_path / "report.md"
    with Store(toy_store) as store:
        summary = ReportStage(mini_settings, toy_protocol, store, model="medgemma", compare_to=None, out=out,
                              now=NOW, run_id=RUN_ID).process("report")
    assert summary["model"] == "google/medgemma-27b-text-it" and summary["model_note"] is None
    prose = json.loads((Path(toy_store) / "report" / RUN_ID / "prose.json").read_text())
    assert set(prose["prose"]["criteria"]) == {"H2", "H4", "H6"}
    paragraphs = [prose["prose"]["summary"], *(v for c in prose["prose"]["criteria"].values() for v in c.values()),
                  prose["prose"]["actions_note"], prose["prose"]["caveats_note"]]
    accepted = [t for t in paragraphs if t not in (FALLBACK, UNAVAILABLE)]
    assert len(accepted) >= 6, "fewer than half the paragraphs survived the back-check — inspect the fixture"
    statuses = [x["status"] for x in GatewayLog.lines(Path(toy_store) / "report" / RUN_ID / "gateway.log")]
    assert statuses[:2] == ["sent", "payload"] and statuses.count("prose_rejected") == len(prose["rejections"])
    md = out.read_text()
    for t in accepted:
        assert t in md
