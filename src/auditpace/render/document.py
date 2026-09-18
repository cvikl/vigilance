"""One document -> one or more rendered pages (S3 design §6)."""
from dataclasses import dataclass

from auditpace.render.browser import Renderer, Word
from auditpace.render.layout import Block, block_html, blocks
from auditpace.render.paginate import paginate
from auditpace.render.templates import CONTENT_BOTTOM, DocMeta, render_html


@dataclass(frozen=True)
class PageRender:
    page_no: int
    page_count: int
    png: bytes
    words: list[Word]


def _html(meta: DocMeta, blks: list[Block], page_no: int, page_count: int) -> str:
    return render_html(meta, "\n".join(block_html(b) for b in blks), page_no, page_count)


def render_document(renderer: Renderer, meta: DocMeta, text: str,
                    content_bottom: float = CONTENT_BOTTOM) -> list[PageRender]:
    """Render once; if the last block ends inside the content box that render is page 1 of 1.
    Otherwise paginate on the measured block extents and re-render each page with its blocks."""
    blks = blocks(text)
    first = renderer.render(_html(meta, blks, 1, 1))
    if not first.blocks or first.blocks[-1][1] <= content_bottom:
        return [PageRender(1, 1, first.png, first.words)]
    try:
        pages = paginate(first.blocks, content_bottom)
    except OverflowError as e:
        raise OverflowError(f"{meta.doc_id}: {e}") from e
    out = []
    for n, idx in enumerate(pages, start=1):
        r = renderer.render(_html(meta, [blks[i] for i in idx], n, len(pages)))
        out.append(PageRender(n, len(pages), r.png, r.words))
    return out
