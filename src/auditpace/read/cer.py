"""Ground-truth-anchored character error rate (S4 design §6).

Both readers transcribe the letterhead and footer that `gt_words` deliberately omits. The reader
text is therefore trimmed to the span between its first and last word that aligns to a gt word
before the Levenshtein distance is taken; junk *inside* that span still counts.
"""
import re

from rapidfuzz.distance import Levenshtein

from auditpace.read.align import align_words, reading_words

_WS = re.compile(r"\s+")


def anchored_cer(gt_words: list[str], reader_text: str) -> float:
    gt = " ".join(gt_words)
    rw = reading_words(reader_text)
    if not gt:
        return 0.0 if not rw else 1.0
    if not rw:
        return 1.0
    pairs = align_words([w for w, _, _ in rw], gt_words)
    if not pairs:
        return 1.0
    first = min(i for i, _ in pairs)
    last = max(i for i, _ in pairs)
    span = _WS.sub(" ", reader_text[rw[first][1]:rw[last][2]]).strip()
    return float(Levenshtein.normalized_distance(gt, span))
