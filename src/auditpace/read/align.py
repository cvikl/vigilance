"""Word-level alignment of a transcript to Tesseract's words (S4 design §6).

Words are compared after `normalise` (lowercase, alphanumerics only). difflib `equal` blocks pair
1:1; `replace` blocks of equal length also pair 1:1 (an OCR typo still sits in the same place);
everything else pairs nothing. Pure-punctuation tokens keep their offsets but never pair and are
not counted in `align_frac`.
"""
import re
from difflib import SequenceMatcher

from auditpace.read.tesseract import TessWord

ALIGN_RULES = (
    "normalise=lower+[^0-9a-z] stripped; SequenceMatcher(autojunk=False); equal pairs 1:1; "
    "replace pairs 1:1 only when equal length; insert/delete/unequal replace pair nothing; "
    "empty-normalised tokens excluded from pairing and align_frac denominator"
)
_NON_ALNUM = re.compile(r"[^0-9a-z]")
_TOKEN = re.compile(r"\S+")


def normalise(word: str) -> str:
    return _NON_ALNUM.sub("", word.lower())


def align_words(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """Pairs (i_a, i_b) between two word lists, compared after normalisation."""
    na = [normalise(w) for w in a]
    nb = [normalise(w) for w in b]
    pairs: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, na, nb, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            pairs.extend((i, j) for i, j in zip(range(i1, i2), range(j1, j2), strict=True) if na[i] and nb[j])
    return pairs


def reading_words(text: str) -> list[tuple[str, int, int]]:
    """Whitespace-delimited tokens of `text` with their (start, end) character offsets."""
    return [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def alignment(reading_text: str, tess_words: list[TessWord]) -> tuple[list[dict], float]:
    """Per paired reading word: {start, end, x0, y0, x1, y1}; plus align_frac = paired / countable."""
    rw = reading_words(reading_text)
    countable = sum(1 for w, _, _ in rw if normalise(w))
    if not countable:
        return [], 0.0
    pairs = align_words([w for w, _, _ in rw], [t.word for t in tess_words])
    entries = []
    for i, j in pairs:
        _, s, e = rw[i]
        t = tess_words[j]
        entries.append({"start": s, "end": e, "x0": t.x0, "y0": t.y0, "x1": t.x1, "y1": t.y1})
    return entries, len(entries) / countable
