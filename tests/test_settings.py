from pathlib import Path

from auditpace.settings import Settings, load_settings


def test_load_settings_from_yaml(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("AUDITPACE_MOCK", raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        """
paths:
  synthea_dir: data/synthea/100k_synthea_covid19_csv
  processed_dir: data/processed
  fixtures_dir: tests/fixtures/mini
models:
  adjudicator: {base_url: "http://localhost:8003/v1", model: "google/medgemma-27b-text-it"}
  reader:      {base_url: "http://localhost:8002/v1", model: "google/medgemma-1.5-4b-it"}
  designer:    {base_url: "http://localhost:8003/v1", model: "google/medgemma-27b-text-it"}
  reporter:    {base_url: "http://localhost:8003/v1", model: "google/medgemma-27b-text-it"}
seed: 42
"""
    )
    s = load_settings(cfg)
    assert isinstance(s, Settings)
    assert s.paths.processed_dir == Path("data/processed")
    assert s.models.adjudicator.model == "google/medgemma-27b-text-it"
    assert s.seed == 42
    assert s.mock is False


def test_mock_flag_from_env(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths: {synthea_dir: a, processed_dir: b, fixtures_dir: c}\nmodels: {}\n")
    monkeypatch.setenv("AUDITPACE_MOCK", "1")
    assert load_settings(cfg).mock is True


def test_synth_defaults_and_override(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths: {synthea_dir: a, processed_dir: b, fixtures_dir: c}\nsynth: {workers: 2}\n")
    s = load_settings(cfg)
    assert (s.synth.model, s.synth.batch_size, s.synth.workers, s.synth.timeout_s) == ("sonnet", 5, 2, 600)


def test_render_config_defaults_and_override(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths: {synthea_dir: x, processed_dir: y, fixtures_dir: z}\n")
    from auditpace.settings import load_settings
    assert load_settings(cfg).render.workers == 4
    cfg.write_text("paths: {synthea_dir: x, processed_dir: y, fixtures_dir: z}\nrender: {workers: 2}\n")
    assert load_settings(cfg).render.workers == 2


def test_read_config_defaults(tmp_path):
    from pathlib import Path

    from auditpace.settings import load_settings

    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths:\n  synthea_dir: x\n  processed_dir: y\n  fixtures_dir: z\n")
    s = load_settings(cfg)
    assert s.read.workers == 8
    assert s.read.max_tokens == 1024
    assert s.read.tessdata_dir == Path("data/tessdata")


def test_adjudicate_config_defaults_and_override(tmp_path):
    from auditpace.settings import load_settings

    cfg = tmp_path / "config.yaml"
    cfg.write_text("paths:\n  synthea_dir: x\n  processed_dir: y\n  fixtures_dir: z\n")
    s = load_settings(cfg)
    assert s.adjudicate.workers == 8
    assert s.adjudicate.max_tokens == 1024
    cfg.write_text("paths: {synthea_dir: x, processed_dir: y, fixtures_dir: z}\nadjudicate: {workers: 2, max_tokens: 512}\n")
    s = load_settings(cfg)
    assert (s.adjudicate.workers, s.adjudicate.max_tokens) == (2, 512)
