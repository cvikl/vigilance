"""The toy report under --no-model is byte-stable. Regenerate deliberately with
`REGEN=1 uv run pytest tests/report/test_snapshot.py` and review the diff."""
import os
from pathlib import Path

from auditpace.report.stage import ReportStage
from auditpace.store import Store
from tests.report.conftest import NOW

EXPECTED = Path(__file__).parent / "expected_report.md"
RUN_ID = "rpt-20260917T120000-00000000"


def test_snapshot(toy_store, toy_protocol, mini_settings, tmp_path, monkeypatch):
    import auditpace.report.stage as S
    monkeypatch.setattr(S, "code_sha", lambda: "0000000")
    out = tmp_path / "report.md"
    with Store(toy_store) as store:
        ReportStage(mini_settings, toy_protocol, store, model=None, compare_to=None, out=out, now=NOW, run_id=RUN_ID).process("report")
    md = out.read_text()
    if os.environ.get("REGEN") == "1":
        EXPECTED.write_text(md)
    assert md == EXPECTED.read_text()
