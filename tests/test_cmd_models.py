from typer.testing import CliRunner

from auditpace.cli import app

runner = CliRunner()


def test_models_check_in_mock_mode_skips(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDITPACE_MOCK", "1")
    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths: {synthea_dir: a, processed_dir: b, fixtures_dir: c}\n"
                   "models: {reader: {base_url: 'http://127.0.0.1:1/v1', model: 'm'}}\n")
    monkeypatch.setenv("AUDITPACE_CONFIG", str(cfg))
    r = runner.invoke(app, ["models", "check"])
    assert r.exit_code == 0 and "mock" in r.stdout


def test_models_check_reports_failure(monkeypatch, tmp_path):
    monkeypatch.delenv("AUDITPACE_MOCK", raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths: {synthea_dir: a, processed_dir: b, fixtures_dir: c}\n"
                   "models: {reader: {base_url: 'http://127.0.0.1:1/v1', model: 'm'}}\n")
    monkeypatch.setenv("AUDITPACE_CONFIG", str(cfg))
    r = runner.invoke(app, ["models", "check"])
    assert r.exit_code == 1 and "FAIL" in r.stdout
