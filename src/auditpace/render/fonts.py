"""Fonts embedded into every rendered page as base64 @font-face rules (S3 design §2 R2, §5).

Chromium ignores `file://` font URLs on a `page.set_content` document, and embedding makes the
render identical on any host regardless of fontconfig.
"""
import base64
import hashlib
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
FONT_FILES = {"Hand": "Caveat[wght].ttf", "Serif": "DejaVuSerif.ttf", "Sans": "DejaVuSans.ttf"}


def _load() -> tuple[str, str]:
    css, digest = [], hashlib.sha256()
    for family, name in FONT_FILES.items():
        data = (ASSETS / "fonts" / name).read_bytes()
        digest.update(data)
        b64 = base64.b64encode(data).decode()
        css.append(
            f"@font-face {{ font-family: '{family}'; src: url(data:font/ttf;base64,{b64}); }}"
        )
    return "\n".join(css), digest.hexdigest()


FONT_CSS, FONT_HASH = _load()
