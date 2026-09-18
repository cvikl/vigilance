from pathlib import Path

import pytest

from auditpace.cohort.stage import CohortStage
from auditpace.protocol import Protocol, load_protocol, lock_protocol
from auditpace.render.stage import RenderStage
from auditpace.settings import Settings, load_settings
from auditpace.store import Store
from auditpace.synth.stage import SynthStage

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "mini"
TESSDATA = ROOT / "data" / "tessdata"


def mini_config_text(processed_dir: Path) -> str:
    """config.yaml for the 5-patient mini cohort. The reader and adjudicator endpoints are the
    real model ids and ports so that fixtures recorded with AUDITPACE_RECORD=1 replay under the
    same cache key."""
    return (
        f"paths:\n  synthea_dir: {MINI/'synthea'}\n  processed_dir: {processed_dir}\n  fixtures_dir: {MINI}\n"
        "models:\n  adjudicator: {base_url: 'http://localhost:8003/v1', model: 'google/medgemma-27b-text-it'}\n"
        "  reader: {base_url: 'http://localhost:8002/v1', model: 'google/medgemma-1.5-4b-it'}\n"
        "  designer: {base_url: 'http://mock/v1', model: 'mock-27b'}\n"
        "  reporter: {base_url: 'http://localhost:8003/v1', model: 'google/medgemma-27b-text-it'}\n"
        # timeout_s=600: a real `claude -p` batch-of-5 authoring call takes 1-3 min; 60s (the
        # original value) made the mini-fixture recording call (test_replay.py) time out and
        # quarantine every attempt before the CLI could finish.
        "synth: {model: sonnet, batch_size: 5, workers: 1, timeout_s: 600}\n"
        f"read: {{workers: 1, max_tokens: 1024, tessdata_dir: {ROOT/'data'/'tessdata'}}}\n"
        "seed: 1\n"
    )


@pytest.fixture
def mini_settings(tmp_path: Path, monkeypatch) -> Settings:
    monkeypatch.setenv("AUDITPACE_MOCK", "1")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(mini_config_text(tmp_path / "processed"))
    return load_settings(cfg)


@pytest.fixture
def locked_protocol(tmp_path: Path) -> Protocol:
    p = tmp_path / "protocol.yaml"
    p.write_text((ROOT / "protocol.yaml").read_text())
    lock_protocol(p)
    return load_protocol(p)


@pytest.fixture
def mini_store(mini_settings, locked_protocol):
    """Store with S1 outputs for the 5-patient mini fixture."""
    with Store(mini_settings.paths.processed_dir) as store:
        CohortStage(mini_settings, locked_protocol, store).run()
        yield store


@pytest.fixture(scope="session")
def renderer():
    """One Chromium for the whole test session. Skips (never fails) when the browser is missing:
    run `uv run playwright install chromium` on a new host."""
    from auditpace.render.browser import Renderer
    try:
        r = Renderer()
    except Exception as e:  # noqa: BLE001 — any launch failure means "no browser here"
        pytest.skip(f"chromium unavailable: {e}")
    yield r
    r.close()


@pytest.fixture(scope="session")
def tessdata_dir() -> Path:
    if not (TESSDATA / "eng.traineddata").exists():
        pytest.skip("tessdata missing: run scripts/fetch_tessdata.sh")
    return TESSDATA


@pytest.fixture(scope="session")
def rendered_mini(tmp_path_factory, renderer) -> Path:
    """processed_dir holding documents/ and pages/ for the mini cohort, built once per session."""
    base = tmp_path_factory.mktemp("rendered_mini")
    processed = base / "processed"
    cfg = base / "config.yaml"
    cfg.write_text(mini_config_text(processed))
    proto = base / "protocol.yaml"
    proto.write_text((ROOT / "protocol.yaml").read_text())
    lock_protocol(proto)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("AUDITPACE_MOCK", "1")
        mp.delenv("AUDITPACE_RECORD", raising=False)
        settings = load_settings(cfg)
        protocol = load_protocol(proto)
        with Store(processed) as store:
            CohortStage(settings, protocol, store).run()
            assert SynthStage(settings, protocol, store).run().n_quarantined == 0
            assert RenderStage(settings, protocol, store).run().n_quarantined == 0
    return processed


@pytest.fixture
def mini_documents(mini_settings, locked_protocol, mini_store, monkeypatch):
    """`documents` for the 5-patient mini cohort, replayed from the recorded claude -p fixture
    (tests/fixtures/mini/responses/, 24 documents) — no CLI, < 1 s."""
    monkeypatch.delenv("AUDITPACE_RECORD", raising=False)
    from auditpace.synth.stage import SynthStage
    summary = SynthStage(mini_settings, locked_protocol, mini_store).run()
    assert summary.n_quarantined == 0, (
        "mini fixture replay failed — re-record per tests/synth/test_replay.py"
    )
    return mini_store
