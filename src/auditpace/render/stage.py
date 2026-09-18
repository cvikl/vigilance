"""Stage 3: render → pages (S3 design §8). One item = one S2 documents partition (batch).

`pages` columns: page_id ("<doc_id>:p<n>"), doc_id, patient_id, doc_type, style, page_no,
page_count, image_path (relative to processed_dir, greyscale JPEG), width, height, gt_words
(json [{word,x0,y0,x1,y1}]), artefact_params (json), text_sha (sha256(documents.text)[:12],
detects a re-authored document even when doc_id set and RENDER_VERSION are unchanged),
render_version, batch_id, protocol_hash.
"""
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
from numpy.random import default_rng

from auditpace.cohort.plant import stable_int
from auditpace.render.artefacts import RANGES, apply, draw_params, transform_words
from auditpace.render.browser import Renderer
from auditpace.render.document import render_document
from auditpace.render.fonts import FONT_HASH
from auditpace.render.layout import FIELD_LINE_PATTERN, LAYOUT_RULES
from auditpace.render.templates import (
    CONTENT_BOTTOM,
    GEOMETRY,
    HEIGHT,
    TEMPLATE_HASH,
    WIDTH,
    DocMeta,
)
from auditpace.stage import Stage

FIELD_RULE = FIELD_LINE_PATTERN
RENDER_VERSION = "render-" + hashlib.sha256(
    (TEMPLATE_HASH + FONT_HASH + RANGES + LAYOUT_RULES + GEOMETRY + FIELD_RULE).encode()
).hexdigest()[:12]


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Batch:
    batch_id: str


class RenderStage(Stage):
    name = "render"

    def __init__(self, settings, protocol, store):
        super().__init__(settings, protocol, store)
        self.seed = protocol.cohort.sample.seed

    def _doc_part(self, batch_id: str) -> Path:
        return self.store.part_dir("documents") / f"{batch_id}.parquet"

    def _page_part(self, batch_id: str) -> Path:
        return self.store.part_dir("pages") / f"{batch_id}.parquet"

    def items(self):
        for p in sorted(self.store.part_dir("documents").glob("*.parquet")):
            yield Batch(p.stem)

    def _current(self, batch_id: str) -> bool:
        """True when the pages partition exists, covers exactly the batch's doc_ids, was
        rendered by this RENDER_VERSION, and every page's text_sha still matches its document's
        current text (catches a re-authored document even when doc_id set and RENDER_VERSION
        haven't changed)."""
        part = self._page_part(batch_id)
        doc = self._doc_part(batch_id)
        if not part.exists() or not doc.exists():
            return False
        have = pd.read_parquet(part, columns=["doc_id", "render_version", "text_sha"])
        docs = pd.read_parquet(doc, columns=["doc_id", "text"])
        want = set(docs.doc_id)
        if set(have.doc_id) != want or not (have.render_version == RENDER_VERSION).all():
            return False
        sha_by_doc = docs.set_index("doc_id").text.map(_text_sha)   # once per doc_id
        return bool((have.text_sha.values == have.doc_id.map(sha_by_doc).values).all())

    def is_done(self, batch: Batch) -> bool:
        return self._current(batch.batch_id)

    def run(self, limit: int | None = None, force: bool = False, workers: int = 1):
        """Refuse stale partitions (no matching documents batch, doc_id mismatch, stale
        text_sha, or old RENDER_VERSION) unless `force`, which deletes them and their page
        image directory first."""
        pdir = self.store.part_dir("pages")
        stale = []
        if pdir.exists():
            for p in sorted(pdir.glob("*.parquet")):
                if not self._current(p.stem):
                    stale.append(p.stem)
        if stale:
            if not force:
                raise ValueError(
                    f"pages/ has stale partitions {stale} (missing documents batch, "
                    f"doc_id mismatch, stale text_sha, or render_version != {RENDER_VERSION}); "
                    "rerun with --force to re-render them"
                )
            for stem in stale:
                (pdir / f"{stem}.parquet").unlink()
                shutil.rmtree(pdir / stem, ignore_errors=True)
        return super().run(limit=limit, force=force, workers=workers)

    def process(self, batch: Batch) -> int:
        docs = pd.read_parquet(self._doc_part(batch.batch_id)).sort_values("doc_id")
        out_dir = self.store.part_dir("pages") / batch.batch_id
        shutil.rmtree(out_dir, ignore_errors=True)   # clear any quarantine leftovers
        out_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        with Renderer() as renderer:
            for d in docs.itertuples(index=False):
                meta = DocMeta(
                    d.doc_id, d.patient_id, d.doc_type, d.style, pd.Timestamp(d.authored_ts)
                )
                text_sha = _text_sha(d.text)
                for pg in render_document(renderer, meta, d.text, CONTENT_BOTTOM):
                    page_id = f"{d.doc_id}:p{pg.page_no}"
                    rng = default_rng(self.seed + stable_int(page_id))
                    params = draw_params(rng)
                    jpg = apply(pg.png, params, rng)
                    words = transform_words(pg.words, params, WIDTH, HEIGHT)
                    rel = Path("pages") / batch.batch_id / f"{d.doc_id}_p{pg.page_no}.jpg"
                    final = self.store.dir / rel
                    tmp = final.with_name(final.name + ".tmp")
                    tmp.write_bytes(jpg)
                    os.replace(tmp, final)
                    rows.append({
                        "page_id": page_id, "doc_id": d.doc_id, "patient_id": d.patient_id,
                        "doc_type": d.doc_type, "style": d.style, "page_no": pg.page_no,
                        "page_count": pg.page_count, "image_path": str(rel),
                        "width": WIDTH, "height": HEIGHT,
                        "gt_words": json.dumps([asdict(w) for w in words]),
                        "artefact_params": json.dumps(params.to_dict()),
                        "text_sha": text_sha,
                        "render_version": RENDER_VERSION, "batch_id": batch.batch_id,
                    })
        df = pd.DataFrame(rows)
        self.store.write_part("pages", batch.batch_id, df, self.protocol.hash)
        print(f"render: {batch.batch_id} ok, {len(df)} pages", flush=True)
        return len(df)
