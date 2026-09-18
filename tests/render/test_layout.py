import html
import re

from auditpace.render.layout import Block, block_html, blocks, body_html

LAB = """VIROLOGY REPORT

Patient: female, 18-39 years
Specimen: Combined nose and throat swab
Date/time reported: 16:52 on 06/03/2020

Result: POSITIVE for SARS-CoV-2 RNA detected.

Comment: Result consistent with current clinical presentation. Please <isolate> & inform IPC."""

NOTE = """CONSULTANT WARD ROUND

Day 1 of admission.  Patient: female.


Observations this morning: HR 108 bpm, SpO2 94% on high-flow oxygen."""


def _words(fragment: str) -> list[str]:
    return [html.unescape(m) for m in re.findall(r'<span class="w">(.*?)</span>', fragment)]


def test_blocks_split_on_blank_lines_and_classify():
    b = blocks(LAB)
    assert [x.kind for x in b] == ["title", "fields", "fields", "fields"]
    assert b[0].lines == ["VIROLOGY REPORT"]
    assert b[1].lines == ["Patient: female, 18-39 years", "Specimen: Combined nose and throat swab",
                          "Date/time reported: 16:52 on 06/03/2020"]
    assert b[3].lines == ["Comment: Result consistent with current clinical presentation. Please <isolate> & inform IPC."]


def test_title_only_when_first_block_is_upper_case():
    assert blocks("Dear Doctor,\n\nThank you.")[0].kind == "para"
    assert blocks("ICU DAILY NOTE 2\n\nx")[0].kind == "title"
    assert blocks("SECOND\n\nTHIRD")[1].kind == "para"  # only the first block can be the title


def test_multiple_blank_lines_and_inner_whitespace():
    b = blocks(NOTE)
    assert len(b) == 3 and b[1].kind == "para" and b[2].kind == "fields"


def test_block_html_wraps_every_token_and_escapes():
    b = blocks(LAB)
    frag = block_html(b[3])
    assert frag.startswith('<div class="blk fields">') and frag.endswith("</div>")
    assert _words(frag) == b[3].lines[0].split()
    assert "&lt;isolate&gt;" in frag and "&amp;" in frag
    fields = block_html(b[1])
    assert fields.count("<br>") == 2 and fields.startswith('<div class="blk fields">')
    assert _words(fields) == " ".join(b[1].lines).split()
    assert block_html(b[0]).startswith('<div class="blk title">')
    para = block_html(blocks(NOTE)[1])
    assert para.startswith('<p class="blk para">') and para.endswith("</p>")
    assert _words(para) == ["Day", "1", "of", "admission.", "Patient:", "female."]


def test_word_contract_over_whole_document():
    for text in (LAB, NOTE):
        assert _words(body_html(blocks(text))) == text.split()


def test_block_is_frozen_dataclass():
    import dataclasses
    assert dataclasses.is_dataclass(Block) and Block.__dataclass_params__.frozen
