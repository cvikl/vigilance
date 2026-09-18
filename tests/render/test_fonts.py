import re

from auditpace.render.fonts import FONT_CSS, FONT_FILES, FONT_HASH


def test_three_families_embedded_as_data_urls():
    assert set(FONT_FILES) == {"Hand", "Serif", "Sans"}
    for family in FONT_FILES:
        assert re.search(rf"@font-face\s*{{\s*font-family:\s*'{family}';\s*src:\s*url\(data:font/ttf;base64,[A-Za-z0-9+/=]+\)", FONT_CSS)
    assert "file://" not in FONT_CSS


def test_font_hash_is_stable_sha256():
    import importlib

    from auditpace.render import fonts
    assert re.fullmatch(r"[0-9a-f]{64}", FONT_HASH)
    assert importlib.reload(fonts).FONT_HASH == FONT_HASH
