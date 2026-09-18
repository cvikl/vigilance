import io

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from auditpace.render.browser import RenderResult, Word
from auditpace.render.layout import blocks, body_html
from auditpace.render.templates import HEIGHT, WIDTH, DocMeta, render_html

TEXT = (
    "WARD ROUND\n\nAdmitted at 00:37 on 07/03/2020 with hypoxaemia. Enoxaparin 40 mg given at "
    "09:40.\n\n"
    "Plan: continue oxygen, chase CRP, physio review."
)


def _render(renderer, style="typed"):
    meta = DocMeta("p1:ward_round", "p1", "ward_round", style, pd.Timestamp("2020-03-07 09:05"))
    return renderer.render(render_html(meta, body_html(blocks(TEXT))))


def _grey(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("L"))


def test_result_shape_and_word_contract(renderer):
    r = _render(renderer)
    assert isinstance(r, RenderResult) and all(isinstance(w, Word) for w in r.words)
    im = Image.open(io.BytesIO(r.png))
    assert im.size == (WIDTH, HEIGHT) and im.mode == "RGB"
    assert [w.word for w in r.words] == TEXT.split()
    assert len(r.blocks) == 3 and all(t < b for t, b in r.blocks)
    assert r.blocks[0][1] <= r.blocks[1][0] <= r.blocks[1][1] <= r.blocks[2][0]


def test_word_boxes_sit_on_ink(renderer):
    g = _grey(_render(renderer).png)
    for w in _render(renderer).words:
        x0, y0, x1, y1 = int(w.x0), int(w.y0), int(np.ceil(w.x1)), int(np.ceil(w.y1))
        assert x1 > x0 and y1 > y0
        assert g[y0:y1, x0:x1].min() < 100, w            # ink inside the box
        assert g[y0:y1, max(0, x0 - 4):x0 - 1].min() > 200, w   # white gutter left of the box
        # and right (ruled lines are lighter than 200)
        assert g[y0:y1, x1 + 1:x1 + 4].min() > 200, w


def test_hyphenated_token_never_wraps(renderer):
    # Chromium soft-wraps at a hyphen inside a word by default; a token that lands at a line
    # end would then get a two-line union box from getBoundingClientRect unless .w forbids it.
    text = "SARS-CoV-2 COVID-19 D-dimer anti-embolism " * 40
    meta = DocMeta("p1:ward_round", "p1", "ward_round", "typed", pd.Timestamp("2020-03-07 09:05"))
    r = renderer.render(render_html(meta, body_html(blocks(text))))
    heights = [w.y1 - w.y0 for w in r.words]
    assert max(heights) <= 1.3 * min(heights)
    assert [w.word for w in r.words] == text.split()


def test_handwritten_uses_embedded_font(renderer):
    typed, hand = _render(renderer), _render(renderer, "handwritten")
    # 32 px vs 21 px
    assert hand.words[0].y1 - hand.words[0].y0 > typed.words[0].y1 - typed.words[0].y0
    assert renderer._page.evaluate("() => document.fonts.check(\"32px 'Hand'\")")


def test_render_is_deterministic(renderer):
    assert _render(renderer).png == _render(renderer).png


def test_context_manager_closes():
    from auditpace.render.browser import Renderer
    with Renderer() as r:
        assert r.render("<html><body><span class='w'>hi</span></body></html>").words[0].word == "hi"
    assert r._browser is None


def test_two_renderers_on_one_thread(renderer):
    from auditpace.render.browser import Renderer
    with Renderer() as a, Renderer() as b:
        assert a.render("<html><body><span class='w'>x</span></body></html>").words[0].word == "x"
        assert b.render("<html><body><span class='w'>y</span></body></html>").words[0].word == "y"
    zr = renderer.render("<html><body><span class='w'>z</span></body></html>")
    assert zr.words[0].word == "z"


def test_init_releases_driver_and_browser_when_page_creation_fails(monkeypatch):
    from playwright.sync_api import Browser

    from auditpace.render import browser

    def boom(self, **kwargs):
        raise RuntimeError("boom")

    before = getattr(browser._local, "refs", 0)
    monkeypatch.setattr(Browser, "new_page", boom)
    with pytest.raises(RuntimeError, match="boom"):
        browser.Renderer()
    assert getattr(browser._local, "refs", 0) == before

    monkeypatch.undo()
    with browser.Renderer() as r:
        html = "<html><body><span class='w'>ok</span></body></html>"
        assert r.render(html).words[0].word == "ok"
