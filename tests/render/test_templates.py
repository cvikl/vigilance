import re

import pandas as pd
import pytest

from auditpace.render.layout import blocks, body_html
from auditpace.render.templates import (
    CONTENT_BOTTOM,
    DOC_TYPES,
    HEIGHT,
    TEMPLATE_HASH,
    WIDTH,
    DocMeta,
    render_html,
)

META = DocMeta("p1:ward_round", "p1", "ward_round", "typed", pd.Timestamp("2020-03-07 09:05"))


def test_constants():
    assert (WIDTH, HEIGHT) == (1240, 1754) and CONTENT_BOTTOM == 1614
    assert DOC_TYPES == (
        "lab_report",
        "ed_clerking",
        "ward_round",
        "icu_note",
        "discharge_summary",
        "clinic_letter",
    )
    assert re.fullmatch(r"[0-9a-f]{64}", TEMPLATE_HASH)


@pytest.mark.parametrize("doc_type", DOC_TYPES)
def test_every_doc_type_renders_a_full_page(doc_type):
    meta = DocMeta(f"p1:{doc_type}", "p1", doc_type, "typed", META.authored_ts)
    body = body_html(blocks("TITLE LINE\n\nSome prose <b>here</b>."))
    out = render_html(meta, body, page_no=2, page_count=3)
    assert out.startswith("<!doctype html>") and "@font-face" in out
    assert "Hospital No: p1" in out and f"Doc: p1:{doc_type}" in out and "07/03/2020 09:05" in out
    assert "Page 2 of 3" in out
    assert f"width:{WIDTH}px" in out and f"height:{HEIGHT}px" in out and "overflow:hidden" in out
    assert body in out  # body inserted verbatim (already escaped by layout)


def test_handwritten_switches_font_and_keeps_typed_letterhead():
    typed = render_html(META, "<p class='blk para'></p>")
    hand_meta = DocMeta("p1:ed_clerking", "p1", "ed_clerking", "handwritten", META.authored_ts)
    hand = render_html(hand_meta, "<p></p>")
    assert "font-family:'Hand'" in hand and "font-family:'Hand'" not in typed
    assert ".letterhead{font-family:'Sans'" in hand


def test_meta_is_escaped():
    out = render_html(DocMeta("<x>", "a&b", "ward_round", "typed", META.authored_ts), "")
    assert "&lt;x&gt;" in out and "a&amp;b" in out


def test_unknown_doc_type_raises():
    with pytest.raises(KeyError):
        render_html(DocMeta("p1:memo", "p1", "memo", "typed", META.authored_ts), "")
