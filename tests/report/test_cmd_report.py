from typer.testing import CliRunner

from auditpace.cli import app
from auditpace.store import Store

runner = CliRunner()


def test_missing_estimates_exits_2(toy_processed, toy_protocol, mini_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    r = runner.invoke(app, ["report", "--no-model", "--protocol", str(tmp_path / "protocol.yaml"),
                            "--out", str(tmp_path / "r.md")])
    assert r.exit_code == 2, r.output
    assert "run `auditpace estimate` first" in r.output


def test_stale_hash_exits_2(toy_store, toy_protocol, mini_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    with Store(toy_store) as s:
        est = s.read("estimates")
        est["protocol_hash"] = "0" * 64
        est.to_parquet(s.path("estimates"), index=False)
    r = runner.invoke(app, ["report", "--no-model", "--protocol", str(tmp_path / "protocol.yaml"),
                            "--out", str(tmp_path / "r.md")])
    assert r.exit_code == 2, r.output
    assert "stale" in r.output.lower()


def test_gateway_violation_exits_2(toy_store, toy_protocol, mini_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    with Store(toy_store) as s:
        al = s.read("alerts")
        al.loc[0, "action"] = "note: patient said 'no'"
        s.write("alerts", al, toy_protocol.hash)
    r = runner.invoke(app, ["report", "--no-model", "--protocol", str(tmp_path / "protocol.yaml"),
                            "--out", str(tmp_path / "r.md")])
    assert r.exit_code == 2, r.output
    assert "alerts[0].action" in r.output


def test_success_writes_out_and_prints_summary(toy_store, toy_protocol, mini_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    out = tmp_path / "docs" / "report.md"
    r = runner.invoke(app, ["report", "--no-model", "--protocol", str(tmp_path / "protocol.yaml"), "--out", str(out)])
    assert r.exit_code == 0, r.output
    assert out.exists() and "report: run_id=rpt-" in r.output and "sent=1 rejected=0 prose_rejected=0" in r.output
    assert "model=none" in r.output and str(out) in r.output
    assert "model_unavailable=0" in r.output
