"""Jinja page templates: one per doc_type, letterhead + body + footer (S3 design §5)."""
import hashlib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from auditpace.render.fonts import FONT_CSS

WIDTH, HEIGHT = 1240, 1754            # A4 at 150 dpi
PAD_TOP, PAD_SIDE, FOOTER_H = 90, 110, 50
CONTENT_BOTTOM = HEIGHT - PAD_TOP - FOOTER_H   # last block must end above this (viewport px)
TYPED_PX, TYPED_LH, HAND_PX, HAND_LH = 21, 1.5, 32, 1.6
# Per-doc_type typed overrides (px, line-height); doc_types not listed use TYPED_PX/TYPED_LH.
# Handwritten style is only offered by ed_clerking/ward_round and always uses HAND_PX/HAND_LH.
SIZES = {"lab_report": (20, 1.45), "icu_note": (20, 1.5), "clinic_letter": (22, 1.5)}
GEOMETRY = (
    f"{WIDTH}x{HEIGHT} pad {PAD_TOP}/{PAD_SIDE} footer {FOOTER_H} content {CONTENT_BOTTOM} "
    f"typed {TYPED_PX}/{TYPED_LH} hand {HAND_PX}/{HAND_LH} sizes {SIZES!r}"
)
DOC_TYPES = (
    "lab_report",
    "ed_clerking",
    "ward_round",
    "icu_note",
    "discharge_summary",
    "clinic_letter",
)

_DIR = Path(__file__).parent / "assets" / "templates"
_ENV = Environment(loader=FileSystemLoader(_DIR), undefined=StrictUndefined, autoescape=False)
TEMPLATE_HASH = hashlib.sha256(
    b"".join(p.read_bytes() for p in sorted(_DIR.glob("*.j2")))
).hexdigest()


@dataclass(frozen=True)
class DocMeta:
    doc_id: str
    patient_id: str
    doc_type: str
    style: str            # "typed" | "handwritten"
    authored_ts: pd.Timestamp


def render_html(meta: DocMeta, body: str, page_no: int = 1, page_count: int = 1) -> str:
    """Render one page. `body` is pre-escaped HTML from `layout.body_html`;
    meta fields are escaped in the template.
    """
    if meta.doc_type not in DOC_TYPES:
        raise KeyError(f"no template for doc_type {meta.doc_type!r}")
    tpl = _ENV.get_template(f"{meta.doc_type}.html.j2")
    hand = meta.style == "handwritten"
    size, line_h = (HAND_PX, HAND_LH) if hand else SIZES.get(meta.doc_type, (TYPED_PX, TYPED_LH))
    return tpl.render(
        meta=meta, body=body, page_no=page_no, page_count=page_count, font_css=FONT_CSS,
        width=WIDTH, height=HEIGHT, pad_top=PAD_TOP, pad_side=PAD_SIDE, footer_h=FOOTER_H,
        font_size=size, line_height=line_h,
        rule_px=round(size * line_h), authored=meta.authored_ts.strftime("%d/%m/%Y %H:%M"),
    )
