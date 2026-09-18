"""Scan artefacts applied to a rendered page, and the matching word-box transform (S3 design §7).

`apply` returns the JPEG bytes it already produces mid-pipeline for the noise/quality step —
there is no PNG re-encode; storage keeps the greyscale JPEG as-is (see stage.py `image_path`).

Pillow's `rotate(angle)` turns the image counter-clockwise for a positive angle about the centre.
In image coordinates (y down) a point at offset (dx, dy) from the centre lands at
(cx + dx*cos t + dy*sin t, cy - dx*sin t + dy*cos t) — verified against Pillow to < 1 px at
±1.5° and 10°.
"""
import io
import math
from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image, ImageFilter

from auditpace.render.browser import Word

ANGLE, BLUR, NOISE, JPEG = 1.5, 0.8, (2.0, 8.0), (60, 80)
RANGES = (
    f"rotate ±{ANGLE}°, blur σ 0–{BLUR}, noise σ {NOISE[0]}–{NOISE[1]}, "
    f"jpeg q {JPEG[0]}–{JPEG[1]}"
)


@dataclass(frozen=True)
class ArtefactParams:
    angle_deg: float
    blur_sigma: float
    noise_sigma: float
    jpeg_q: int

    def to_dict(self) -> dict:
        return asdict(self)


def draw_params(rng: np.random.Generator) -> ArtefactParams:
    return ArtefactParams(
        angle_deg=float(rng.uniform(-ANGLE, ANGLE)),
        blur_sigma=float(rng.uniform(0.0, BLUR)),
        noise_sigma=float(rng.uniform(*NOISE)),
        jpeg_q=int(rng.integers(JPEG[0], JPEG[1] + 1)),
    )


def apply(png: bytes, p: ArtefactParams, rng: np.random.Generator) -> bytes:
    """Greyscale + rotate + blur + noise + JPEG-encode `png`; return the JPEG bytes as-is
    (the JPEG round-trip at `p.jpeg_q` is the artefact and also the stored page image —
    no PNG re-encode)."""
    im = Image.open(io.BytesIO(png)).convert("L")
    im = im.rotate(p.angle_deg, resample=Image.BICUBIC, expand=False, fillcolor=255)
    if p.blur_sigma > 0:
        im = im.filter(ImageFilter.GaussianBlur(p.blur_sigma))
    if p.noise_sigma > 0:
        arr = np.asarray(im, dtype=np.float32) + rng.normal(
            0.0, p.noise_sigma, size=(im.height, im.width)
        )
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "L")
    jpg = io.BytesIO()
    im.save(jpg, "JPEG", quality=p.jpeg_q)
    return jpg.getvalue()


def _rotate_point(
    x: float, y: float, angle_deg: float, cx: float, cy: float
) -> tuple[float, float]:
    t = math.radians(angle_deg)
    c, s = math.cos(t), math.sin(t)
    dx, dy = x - cx, y - cy
    return cx + dx * c + dy * s, cy - dx * s + dy * c


def transform_words(words: list[Word], p: ArtefactParams, width: int, height: int) -> list[Word]:
    cx, cy = width / 2, height / 2
    out = []
    for w in words:
        pts = [
            _rotate_point(x, y, p.angle_deg, cx, cy)
            for x, y in ((w.x0, w.y0), (w.x1, w.y0), (w.x0, w.y1), (w.x1, w.y1))
        ]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        out.append(
            Word(
                w.word,
                max(0, math.floor(min(xs))),
                max(0, math.floor(min(ys))),
                min(width, math.ceil(max(xs))),
                min(height, math.ceil(max(ys))),
            )
        )
    return out
