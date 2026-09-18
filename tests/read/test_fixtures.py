import json
from pathlib import Path

from auditpace.render.stage import RENDER_VERSION


def test_mini_pages_has_pages_and_images(mini_settings, locked_protocol, mini_pages):
    pages = mini_pages.read("pages")
    assert len(pages) >= 24
    assert (pages.render_version == RENDER_VERSION).all()
    assert (pages.protocol_hash == locked_protocol.hash).all()
    root = Path(mini_settings.paths.processed_dir)
    for r in pages.itertuples():
        assert (root / r.image_path).exists()
        assert json.loads(r.gt_words)


def test_mini_pages_copies_are_independent(mini_settings, mini_pages, rendered_mini):
    assert Path(mini_settings.paths.processed_dir) != rendered_mini


def test_tessdata_present(tessdata_dir):
    assert (tessdata_dir / "eng.traineddata").stat().st_size > 1_000_000
