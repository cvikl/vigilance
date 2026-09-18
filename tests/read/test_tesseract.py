import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from auditpace.read.tesseract import TESSDATA_SHA, Tesseract, TessWord


def _norm(w: str) -> str:
    return re.sub(r"[^0-9a-z]", "", w.lower())


def _typed_page(mini_settings, mini_pages):
    pages = mini_pages.read("pages")
    row = pages[pages["style"] == "typed"].sort_values("page_id").iloc[0]
    return Path(mini_settings.paths.processed_dir) / row.image_path, json.loads(row.gt_words)


def test_missing_tessdata_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="fetch_tessdata"):
        Tesseract(tmp_path)


def test_sha_is_pinned():
    assert re.fullmatch(r"[0-9a-f]{64}", TESSDATA_SHA)


def test_words_cover_ground_truth(mini_settings, mini_pages, tessdata_dir):
    img, gt = _typed_page(mini_settings, mini_pages)
    words = Tesseract(tessdata_dir).words(img)
    assert words and all(isinstance(w, TessWord) for w in words)
    got = {_norm(w.word) for w in words} - {""}
    want = [_norm(w["word"]) for w in gt if _norm(w["word"])]
    hit = sum(1 for w in want if w in got)
    assert hit / len(want) >= 0.8, f"{hit}/{len(want)} gt words recognised"
    assert all(0 <= w.conf <= 100 for w in words)


def test_boxes_inside_image_and_on_ink(mini_settings, mini_pages, tessdata_dir):
    img, _ = _typed_page(mini_settings, mini_pages)
    g = np.asarray(Image.open(img).convert("L"))
    h, w = g.shape
    words = Tesseract(tessdata_dir).words(img)
    for t in words:
        assert 0 <= t.x0 < t.x1 <= w and 0 <= t.y0 < t.y1 <= h, t
        assert all(isinstance(v, int) for v in (t.x0, t.y0, t.x1, t.y1))
    on_ink = sum(1 for t in words if g[t.y0:t.y1, t.x0:t.x1].min() < 100)
    assert on_ink / len(words) >= 0.95


def test_thread_safe_and_deterministic(mini_settings, mini_pages, tessdata_dir):
    img, _ = _typed_page(mini_settings, mini_pages)
    t = Tesseract(tessdata_dir)
    with ThreadPoolExecutor(2) as pool:
        a, b = list(pool.map(t.words, [img, img]))
    assert a == b == t.words(img)
