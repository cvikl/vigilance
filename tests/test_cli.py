from typer.testing import CliRunner

from auditpace.cli import app

runner = CliRunner()


def test_version_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "auditpace 0.1.0" in result.stdout


def test_adjudicate_exits_2_without_upstream_tables(mini_settings, locked_protocol, mini_store, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    result = runner.invoke(app, ["adjudicate", "--protocol", str(tmp_path / "protocol.yaml")])
    assert result.exit_code == 2, result.output
    assert "missing documents" in result.output


def test_estimate_exits_2_without_verdicts(mini_settings, locked_protocol, mini_store, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    result = runner.invoke(app, ["estimate", "--protocol", str(tmp_path / "protocol.yaml")])
    assert result.exit_code == 2, result.output
    assert "missing verdicts" in result.output


def test_workbench_exits_2_without_verdicts(mini_settings, locked_protocol, mini_store, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    result = runner.invoke(app, ["workbench", "--protocol", str(tmp_path / "protocol.yaml")])
    assert result.exit_code == 2, result.output
    assert "missing verdicts" in result.output
