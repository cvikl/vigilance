from typer.testing import CliRunner

from auditpace.cli import app
from tests.conftest import mini_config_text

runner = CliRunner()


def test_workbench_builds_app_and_prints_urls(toy_processed, toy_protocol, tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(mini_config_text(toy_processed))
    monkeypatch.setenv("AUDITPACE_CONFIG", str(cfg))
    served = {}
    monkeypatch.setattr("auditpace.cmd_workbench.uvicorn.run", lambda a, **kw: served.update(kw, app=a))
    result = runner.invoke(app, ["workbench", "--protocol", str(tmp_path / "protocol.yaml"), "--port", "9999"])
    assert result.exit_code == 0, result.output
    assert served["port"] == 9999 and served["app"].state.snapshot is not None
    assert "http://127.0.0.1:9999/queue?demo=1" in result.output
