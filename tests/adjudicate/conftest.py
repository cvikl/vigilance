"""Fixtures for S5 tests. The mini cohort is rendered once per session (tests/conftest.py) and
read once per session here by replaying the recorded S4 transcripts, so a stage test costs a copy."""
import shutil
from pathlib import Path

import pytest

from auditpace.models import ModelClient
from auditpace.protocol import load_protocol
from auditpace.read.stage import ReadStage
from auditpace.settings import load_settings
from auditpace.store import Store


@pytest.fixture(scope="session")
def read_mini(rendered_mini: Path, tessdata_dir: Path, tmp_path_factory) -> Path:
    """processed_dir holding documents/, pages/ and readings/ for the mini cohort."""
    base = tmp_path_factory.mktemp("read_mini")
    processed = base / "processed"
    shutil.copytree(rendered_mini, processed)
    cfg, proto = rendered_mini.parent / "config.yaml", rendered_mini.parent / "protocol.yaml"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("AUDITPACE_MOCK", "1")
        mp.delenv("AUDITPACE_RECORD", raising=False)
        mp.setenv("AUDITPACE_CONFIG", str(cfg))
        settings = load_settings(cfg).model_copy(update={"paths": load_settings(cfg).paths.model_copy(update={"processed_dir": processed})})
        protocol = load_protocol(proto)
        with Store(processed) as store:
            client = ModelClient(settings.models.reader, mock=True, fixtures_dir=settings.paths.fixtures_dir, record=False)
            s = ReadStage(settings, protocol, store, client=client).run()
            assert s.n_quarantined == 0, "S4 mini replay failed — see tests/read/test_replay.py"
    return processed


@pytest.fixture
def mini_readings(mini_settings, locked_protocol, mini_store, read_mini) -> Store:
    """mini_store plus documents/, pages/ and readings/ copied from the session read."""
    dst = Path(mini_settings.paths.processed_dir)
    for name in ("documents", "pages", "readings"):
        shutil.copytree(read_mini / name, dst / name, dirs_exist_ok=True)
    return mini_store
