"""Text -> blocks -> HTML with every word in a <span class="w"> (S3 design §4).

A word is a `str.split()` token with its punctuation attached: the same tokenisation S4's
normaliser and S5's `fact_needle` verbatim check rely on. Layout never rewrites text.
"""
import html
import re
from dataclasses import dataclass

LAYOUT_RULES = (
    "layout-v1: blank-line blocks; upper-case first block = title; "
    "key: value lines = fields"
)

FIELD_LINE_PATTERN = r"^[A-Za-z0-9 /()%-]{2,40}:\s"
_FIELD_LINE = re.compile(FIELD_LINE_PATTERN)


@dataclass(frozen=True)
class Block:
    kind: str        # "title" | "fields" | "para"
    lines: list[str]


def _is_title(text: str) -> bool:
    return any(c.isalpha() for c in text) and text.upper() == text


def blocks(text: str) -> list[Block]:
    out: list[Block] = []
    for i, chunk in enumerate(re.split(r"\n\s*\n", text.strip())):
        lines = [ln.strip() for ln in chunk.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if i == 0 and _is_title(" ".join(lines)):
            kind = "title"
        elif all(_FIELD_LINE.match(ln) for ln in lines):
            kind = "fields"
        else:
            kind = "para"
        out.append(Block(kind, lines))
    return out


def _spans(line: str) -> str:
    return " ".join(f'<span class="w">{html.escape(tok)}</span>' for tok in line.split())


def block_html(block: Block) -> str:
    if block.kind == "para":
        return f'<p class="blk para">{" ".join(_spans(ln) for ln in block.lines)}</p>'
    inner = "<br>".join(_spans(ln) for ln in block.lines)
    return f'<div class="blk {block.kind}">{inner}</div>'


def body_html(blocks_: list[Block]) -> str:
    return "\n".join(block_html(b) for b in blocks_)
