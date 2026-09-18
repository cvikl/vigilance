import io

import numpy as np
import pytest
from numpy.random import default_rng
from PIL import Image, ImageDraw

from auditpace.render.artefacts import RANGES, ArtefactParams, apply, draw_params, transform_words
from auditpace.render.browser import Word

W, H = 400, 600


def _page(box=(300, 50, 380, 80)) -> bytes:
    im = Image.new("RGB", (W, H), "white")
    ImageDraw.Draw(im).rectangle(box, fill="black")
    buf = io.BytesIO(); im.save(buf, "PNG"); return buf.getvalue()


def _dark_bounds(png: bytes):
    a = np.asarray(Image.open(io.BytesIO(png)).convert("L"))
    ys, xs = np.where(a < 128)
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_draw_params_within_ranges_and_seeded():
    p = draw_params(default_rng(7))
    assert -1.5 <= p.angle_deg <= 1.5 and 0 <= p.blur_sigma <= 0.8 and 2 <= p.noise_sigma <= 8
    assert 60 <= p.jpeg_q <= 80 and isinstance(p.jpeg_q, int)
    assert draw_params(default_rng(7)) == p and draw_params(default_rng(8)) != p
    assert set(p.to_dict()) == {"angle_deg", "blur_sigma", "noise_sigma", "jpeg_q"}
    assert "1.5" in RANGES and "0.8" in RANGES


def test_apply_is_deterministic_greyscale_same_size():
    p = draw_params(default_rng(1))
    a, b = apply(_page(), p, default_rng(1)), apply(_page(), p, default_rng(1))
    assert a == b
    im = Image.open(io.BytesIO(a))
    assert im.format == "JPEG" and im.mode == "L" and im.size == (W, H)
    assert apply(_page(), p, default_rng(2)) != a   # noise draw differs


@pytest.mark.parametrize("angle", [1.5, -1.5, 10.0])
def test_transformed_box_contains_rotated_ink(angle):
    p = ArtefactParams(angle, 0.0, 0.0, 95)          # rotation only
    out = apply(_page(), p, default_rng(0))
    x0, y0, x1, y1 = _dark_bounds(out)
    (w,) = transform_words([Word("blk", 300, 50, 380, 80)], p, W, H)
    assert w.word == "blk" and all(isinstance(v, int) for v in (w.x0, w.y0, w.x1, w.y1))
    assert w.x0 <= x0 and w.y0 <= y0 and w.x1 >= x1 and w.y1 >= y1      # covers all ink
    assert (w.x1 - w.x0) <= (x1 - x0) + 4 and (w.y1 - w.y0) <= (y1 - y0) + 4   # and is tight


def test_transform_clips_to_page():
    p = ArtefactParams(1.5, 0, 0, 70)
    (w,) = transform_words([Word("edge", 0, 0, W, H)], p, W, H)
    assert (w.x0, w.y0, w.x1, w.y1) == (0, 0, W, H)


def test_zero_angle_is_identity_up_to_rounding():
    (w,) = transform_words([Word("a", 10.2, 20.7, 30.1, 40.9)], ArtefactParams(0, 0, 0, 70), W, H)
    assert (w.x0, w.y0, w.x1, w.y1) == (10, 20, 31, 41)
