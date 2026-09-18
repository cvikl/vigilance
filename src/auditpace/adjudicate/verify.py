"""Verify an adjudicator quote against a page's reading_text and map it to word boxes (S5 design
§6, S4 design §8 contract).

Both quote and text are reduced to lowercase alphanumerics; a per-character map carries each
normalised char's raw offset, so the matched span is returned as raw `[s, e)` offsets that
`alignment` can be queried with directly. Punctuation, whitespace and MedGemma's line breaks
therefore never break a match. The first occurrence wins (looped passages — handoff-s5).
`found` = the quote is in the transcript; `verified` = found and at least one aligned word box
overlaps the span. `bboxes` non-empty ⇔ `verified` (design spec §5 invariant).
"""
from dataclasses import dataclass, field

MIN_QUOTE_CHARS = 8   # a bare time string normalises to 14; anything under 8 matches by accident
VERIFY_RULES = (
    "normalise=lower+[^0-9a-z] dropped with per-char raw-offset map; first occurrence; per-page "
    "search within cited doc_id in page_no order; min 8 normalised chars; "
    "bboxes=alignment entries overlapping [s,e)"
)
_ALNUM = frozenset("0123456789abcdefghijklmnopqrstuvwxyz")


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """(normalised, idx): idx[k] is the raw offset of normalised char k."""
    chars: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        c = ch.lower()
        if len(c) == 1 and c in _ALNUM:
            chars.append(c)
            idx.append(i)
    return "".join(chars), idx


@dataclass
class PageReading:
    page_id: str
    page_no: int
    reading_text: str
    alignment: list[dict]
    norm: str = field(init=False, repr=False)
    idx: list[int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.norm, self.idx = normalise_with_map(self.reading_text)


def _locate(q: str, norm: str, idx: list[int]) -> tuple[int, int] | None:
    if len(q) < MIN_QUOTE_CHARS:
        return None
    k = norm.find(q)
    if k < 0:
        return None
    return idx[k], idx[k + len(q) - 1] + 1


def find_quote(quote: str, text: str) -> tuple[int, int] | None:
    """Raw `[s, e)` of the first normalised occurrence of `quote` in `text`, or None."""
    q, _ = normalise_with_map(quote)
    norm, idx = normalise_with_map(text)
    return _locate(q, norm, idx)


def bboxes_for(alignment: list[dict], s: int, e: int) -> list[dict]:
    return [{"x0": a["x0"], "y0": a["y0"], "x1": a["x1"], "y1": a["y1"]}
            for a in alignment if a["start"] < e and a["end"] > s]


def verify_evidence(kind: str, doc_id: str, quote: str, pages: list[PageReading]) -> dict:
    """One evidence entry. `pages` are the cited document's readings (empty for an unknown doc)."""
    out = {"kind": kind, "doc_id": doc_id, "page_id": None, "quote": quote, "start": None, "end": None,
           "bboxes": [], "found": False, "verified": False}
    q, _ = normalise_with_map(quote)
    for p in sorted(pages, key=lambda p: p.page_no):
        span = _locate(q, p.norm, p.idx)
        if span is None:
            continue
        s, e = span
        boxes = bboxes_for(p.alignment, s, e)
        out.update(page_id=p.page_id, start=s, end=e, found=True, bboxes=boxes, verified=bool(boxes))
        return out
    return out
