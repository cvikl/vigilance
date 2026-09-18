"""Batch validation (S2 design §8): coverage, verbatim facts, UK register, length. Returns messages;
never raises, so the stage can feed them back to the model on retry."""
import re

from auditpace.synth.plan import DocSpec

_BANNED = ["ER", "attending physician", "resident physician", "intern", "acetaminophen", "Tylenol", "EKG", "epinephrine",
           "mg/dL", "Foley", "code status", "nurse practitioner"]
BANLIST = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in _BANNED) + r")\b", re.IGNORECASE)
MIN_WORDS, MAX_WORDS = 60, 600
TERMINAL_PUNCTUATION = ".!?"


def fact_needle(text: str) -> str:
    """The string a planted fact is verified against: terminal punctuation stripped, because the
    model may continue a sentence past a fact's final full stop. S5 must use this, not the raw
    text."""
    return text.rstrip(TERMINAL_PUNCTUATION)


def validate_batch(planned: dict[str, DocSpec], returned: dict) -> list[str]:
    errors: list[str] = []
    docs = returned.get("documents") if isinstance(returned, dict) else None
    if not isinstance(docs, list):
        return ["response has no 'documents' list"]
    texts: dict[str, str] = {}
    for d in docs:
        if not isinstance(d, dict) or not isinstance(d.get("doc_id"), str) or not isinstance(d.get("text"), str):
            errors.append(f"malformed document entry: {str(d)[:80]!r}")
            continue
        if d["doc_id"] in texts:
            errors.append(f"duplicate doc_id {d['doc_id']}")
            continue
        texts[d["doc_id"]] = d["text"]
    for aid in planned:
        if aid not in texts:
            errors.append(f"missing document {aid}")
    for aid in texts:
        if aid not in planned:
            errors.append(f"unexpected document {aid}")
    for aid, spec in planned.items():
        text = texts.get(aid)
        if text is None:
            continue
        for f in spec.facts:
            needle = fact_needle(f.text)
            if needle not in text:
                errors.append(f"{aid}: fact {f.fact_id} not verbatim: {f.text!r}")
        hits = sorted({m.group(0) for m in BANLIST.finditer(text)})
        if hits:
            errors.append(f"{aid}: US-register terms {hits}")
        n = len(text.split())
        if not MIN_WORDS <= n <= MAX_WORDS:
            errors.append(f"{aid}: {n} words, expected {MIN_WORDS}-{MAX_WORDS}")
    return errors
