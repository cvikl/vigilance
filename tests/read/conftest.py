"""Fixtures for S4 tests. The mini cohort is rendered once per session (Chromium, ~10 s) and
copied into each test's processed_dir, so a read-stage test costs a copy, not a render."""
import shutil
from pathlib import Path

import pytest

from auditpace.store import Store


@pytest.fixture
def mini_pages(mini_settings, locked_protocol, mini_store, rendered_mini) -> Store:
    """mini_store plus documents/ and pages/ (parquet + JPEGs) copied from the session render."""
    dst = Path(mini_settings.paths.processed_dir)
    for name in ("documents", "pages"):
        shutil.copytree(rendered_mini / name, dst / name, dirs_exist_ok=True)
    return mini_store
