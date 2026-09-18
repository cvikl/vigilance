"""Stage 4: read → readings (S4 design §7-8). One item = one S3 pages partition (batch).

`readings` columns: page_id, doc_id, patient_id, doc_type, style, page_no, tess_words (json
[{word,conf,x0,y0,x1,y1}]), tess_text, medgemma_text ("" on a reader-failure fallback, but the raw
transcript on a low-alignment fallback — see MIN_ALIGN_FRAC), reading_text (what S5/S7 use),
reader_used (medgemma|tesseract), alignment (json [{start,end,x0,y0,x1,y1}] - char offsets
into reading_text), align_frac, cer_tess, cer_medgemma (NaN on fallback), n_gt_words,
read_version, render_version (copied from the source page), batch_id, protocol_hash.

A page whose first transcription attempt hits finish_reason=length is retried once with
`repetition_penalty=RETRY_REPETITION_PENALTY` — MedGemma 1.5 4B can enter a greedy-decoding
runaway repetition loop on some pages, and the penalty was found (2026-09-15, on the mini
cohort) to resolve it; if the retry also fails with a `ReaderError` the page falls back to the
raw Tesseract text (reader_used=tesseract, medgemma_text="", cer_medgemma=NaN). A transport
failure (`httpx.HTTPError`) gets the same one retry, but if the retry also fails it is re-raised
rather than falling back — `Stage.run` quarantines the whole batch, and a plain re-run (no
`--force`) resumes it, since a transport error says nothing about whether the model can read the
page. A transcript that returns cleanly but barely aligns to Tesseract's words (a refusal string,
a self-terminated repetition loop that never hit finish_reason=length, or otherwise garbage) is
also treated as a reader failure — see MIN_ALIGN_FRAC below.
"""
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
import pandas as pd
from tesserocr import PSM

from auditpace.models import client_for
from auditpace.read.align import ALIGN_RULES, alignment
from auditpace.read.cer import anchored_cer
from auditpace.read.reader import READ_PROMPT, ReaderError, transcribe
from auditpace.read.tesseract import DPI, TESSDATA_SHA, Tesseract
from auditpace.stage import Stage

RETRIES = 1   # one retry, then fall back to Tesseract text for that page

# MedGemma 1.5 4B was observed (2026-09-15) to loop deterministically on one mini-cohort page,
# repeating the same sentence past the 1024-token cap under greedy decoding (temperature=0.0).
# A probe found repetition_penalty=1.1 gives a clean 505-token stop on that page (frequency_penalty
# and presence_penalty did not help); the retry attempt in _transcribe uses it. 1.1 broke the loop
# on that one mini page but 0 of 159 loops in the 2026-09-15 full run (2.5% fallback, mostly
# ed_clerking); a follow-up probe found 1.3 broke all probed loops (1.1 and 1.2 still looped),
# at a small accuracy cost on clean pages (+0.01-0.09 anchored CER) that is acceptable since the
# penalty only ever applies to the retry attempt.
RETRY_REPETITION_PENALTY = 1.3

# On the 2026-09-15 full run three pages passed the finish_reason/empty guard yet were garbage
# (a refusal "I am sorry, but I cannot fulfill your request. I am a text-based AI and cannot
# process images.", a self-terminated repetition loop, and a 0.71-CER page) with align_frac
# 0.17-0.27, while the lowest legitimate page was 0.375; below this threshold the transcript is
# discarded in favour of Tesseract text.
MIN_ALIGN_FRAC = 0.30


def read_version(reader_model: str, max_tokens: int) -> str:
    h = hashlib.sha256(
        (
            READ_PROMPT + TESSDATA_SHA + ALIGN_RULES + reader_model + str(RETRY_REPETITION_PENALTY)
            + str(MIN_ALIGN_FRAC) + str(RETRIES) + f"{DPI}:{PSM.AUTO}" + str(max_tokens)
        ).encode()
    )
    return "read-" + h.hexdigest()[:12]


@dataclass(frozen=True)
class Batch:
    batch_id: str


class ReadStage(Stage):
    name = "read"

    def __init__(self, settings, protocol, store, client=None, tesseract=None):
        super().__init__(settings, protocol, store)
        self.client = client if client is not None else client_for(settings, "reader")
        self.tesseract = tesseract if tesseract is not None else Tesseract(settings.read.tessdata_dir)
        self.version = read_version(settings.models.reader.model, settings.read.max_tokens)
        self.max_tokens = settings.read.max_tokens
        self.n_fallback = 0

    def _page_part(self, batch_id: str) -> Path:
        return self.store.part_dir("pages") / f"{batch_id}.parquet"

    def _read_part(self, batch_id: str) -> Path:
        return self.store.part_dir("readings") / f"{batch_id}.parquet"

    def items(self):
        for p in sorted(self.store.part_dir("pages").glob("*.parquet")):
            yield Batch(p.stem)

    def _current(self, batch_id: str) -> bool:
        """True when the readings partition exists, covers exactly the pages partition's page_ids,
        was produced by this read_version, and every row's render_version matches its page's."""
        part, pages = self._read_part(batch_id), self._page_part(batch_id)
        if not part.exists() or not pages.exists():
            return False
        have = pd.read_parquet(part, columns=["page_id", "read_version", "render_version"])
        want = pd.read_parquet(pages, columns=["page_id", "render_version"]).set_index("page_id").render_version
        if set(have.page_id) != set(want.index) or not (have.read_version == self.version).all():
            return False
        return bool((have.render_version.values == want.loc[have.page_id].values).all())

    def is_done(self, batch: Batch) -> bool:
        return self._current(batch.batch_id)

    def run(self, limit: int | None = None, force: bool = False, workers: int = 1):
        """Refuse stale readings partitions (no pages batch, page_id mismatch, stale
        render_version, or old read_version) unless `force`, which deletes them first."""
        rdir = self.store.part_dir("readings")
        stale = [p.stem for p in sorted(rdir.glob("*.parquet"))] if rdir.exists() else []
        stale = [s for s in stale if not self._current(s)]
        if stale:
            if not force:
                raise ValueError(
                    f"readings/ has stale partitions {stale} (missing pages batch, page_id mismatch, "
                    f"stale render_version, or read_version != {self.version}); rerun with --force"
                )
            for stem in stale:
                (rdir / f"{stem}.parquet").unlink()
        self.n_fallback = 0
        summary = super().run(limit=limit, force=force, workers=workers)
        self.n_fallback = sum(o["fallback"] for o in self.outputs)
        print(f"read: fallback={self.n_fallback}", flush=True)
        return summary

    def _transcribe(self, image: Path) -> str | None:
        """One retry on `ReaderError` or `httpx.HTTPError`. After the retry: a `ReaderError` still
        falls back to Tesseract text for this page (returns None); an `httpx.HTTPError` is
        re-raised — a transport failure says nothing about whether the model can read the page, so
        `Stage.run` quarantines the whole batch and a plain re-run (no `--force`) resumes it."""
        for attempt in range(RETRIES + 1):
            penalty = RETRY_REPETITION_PENALTY if attempt > 0 else None
            try:
                return transcribe(self.client, image, self.max_tokens, repetition_penalty=penalty)
            except (ReaderError, httpx.HTTPError) as e:
                if attempt == RETRIES:
                    if isinstance(e, httpx.HTTPError):
                        raise
                    print(f"read: fallback to tesseract for {image.name}: {e}", flush=True)
                    return None
        return None

    def process(self, batch: Batch) -> dict:
        pages = pd.read_parquet(self._page_part(batch.batch_id)).sort_values("page_id")
        rows, fallback = [], 0
        for p in pages.itertuples(index=False):
            image = self.store.dir / p.image_path
            tess = self.tesseract.words(image)                      # exceptions quarantine the batch
            tess_text = " ".join(t.word for t in tess)
            gt_words = [w["word"] for w in json.loads(p.gt_words)]
            medgemma_text = self._transcribe(image)
            if medgemma_text is None:
                fallback += 1
                reading_text, reader_used, medgemma_text = tess_text, "tesseract", ""
                cer_mg = math.nan
                entries, frac = alignment(reading_text, tess)
            else:
                reading_text, reader_used = medgemma_text, "medgemma"
                cer_mg = anchored_cer(gt_words, medgemma_text)
                entries, frac = alignment(reading_text, tess)
                if frac < MIN_ALIGN_FRAC:
                    # Transcript came back clean (no finish_reason=length, non-empty) but barely
                    # aligns to Tesseract's words — a refusal, a self-terminated loop, or other
                    # garbage. medgemma_text is KEPT (still useful evidence for S8); reading_text
                    # falls back to Tesseract text exactly as on a reader failure.
                    fallback += 1
                    print(f"read: low-alignment fallback for {p.page_id}: align_frac={frac:.2f}", flush=True)
                    reading_text, reader_used = tess_text, "tesseract"
                    cer_mg = math.nan
                    entries, frac = alignment(tess_text, tess)
            rows.append({
                "page_id": p.page_id, "doc_id": p.doc_id, "patient_id": p.patient_id,
                "doc_type": p.doc_type, "style": p.style, "page_no": int(p.page_no),
                "tess_words": json.dumps([asdict(t) for t in tess]), "tess_text": tess_text,
                "medgemma_text": medgemma_text, "reading_text": reading_text, "reader_used": reader_used,
                "alignment": json.dumps(entries), "align_frac": frac,
                "cer_tess": anchored_cer(gt_words, tess_text), "cer_medgemma": cer_mg,
                "n_gt_words": len(gt_words),
                "read_version": self.version, "render_version": p.render_version, "batch_id": batch.batch_id,
            })
        df = pd.DataFrame(rows)
        self.store.write_part("readings", batch.batch_id, df, self.protocol.hash)
        print(f"read: {batch.batch_id} ok, {len(df)} pages, {fallback} fallback", flush=True)
        return {"pages": len(df), "fallback": fallback}
