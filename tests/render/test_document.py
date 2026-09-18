import pandas as pd
import pytest

from auditpace.render.document import PageRender, render_document
from auditpace.render.templates import CONTENT_BOTTOM, DocMeta

META = DocMeta(
    "p1:discharge_summary", "p1", "discharge_summary", "typed", pd.Timestamp("2020-03-22 21:30")
)
PARA = (
    "Observations remained stable overnight and the patient mobilised independently on the ward. "
    * 4
)
# ~ 6 x 4 lines: fits one A4 page, not a 700 px box
TEXT = "DISCHARGE SUMMARY\n\n" + "\n\n".join([PARA] * 6)


def test_single_page_when_it_fits(renderer):
    pages = render_document(renderer, META, TEXT)
    assert len(pages) == 1 and isinstance(pages[0], PageRender)
    assert (pages[0].page_no, pages[0].page_count) == (1, 1)
    assert [w.word for w in pages[0].words] == TEXT.split()


def test_multi_page_partitions_words_exactly(renderer):
    pages = render_document(renderer, META, TEXT, content_bottom=700)
    assert len(pages) >= 2
    assert [p.page_no for p in pages] == list(range(1, len(pages) + 1))
    assert {p.page_count for p in pages} == {len(pages)}
    assert [w.word for p in pages for w in p.words] == TEXT.split()
    for p in pages:
        assert p.words and max(w.y1 for w in p.words) <= 700 + 1   # nothing rendered below the box


def test_overflowing_block_raises_with_doc_id(renderer):
    with pytest.raises(OverflowError, match=r"p1:discharge_summary: block \d+ is"):
        render_document(renderer, META, TEXT, content_bottom=300)


def test_default_box_matches_template_constant():
    import inspect
    assert inspect.signature(render_document).parameters["content_bottom"].default == CONTENT_BOTTOM
