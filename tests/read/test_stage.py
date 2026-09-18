import json
import math
from pathlib import Path

import httpx
import pandas as pd
import pytest
from typer.testing import CliRunner

from auditpace.cli import app
from auditpace.read.reader import ReaderError
from auditpace.read.stage import RETRY_REPETITION_PENALTY, Batch, ReadStage, read_version
from auditpace.render.stage import RENDER_VERSION


class GTClient:
    """Stub reader: returns the page's own gt text (found by image bytes), with a letterhead line
    prepended and a line break every 8 words, so alignment/CER see realistic input."""

    def __init__(self, settings, store, fail_times=0, exc=ReaderError("boom")):
        pages = store.read("pages")
        root = Path(settings.paths.processed_dir)
        self.by_bytes = {(root / r.image_path).read_bytes(): json.loads(r.gt_words) for r in pages.itertuples()}
        self.fail_times, self.exc, self.calls = fail_times, exc, 0
        self.extras = []

    def chat_full(self, messages, *, images, temperature, max_tokens, extra=None):
        self.calls += 1
        self.extras.append(extra)
        if self.calls <= self.fail_times:
            raise self.exc
        words = [w["word"] for w in self.by_bytes[Path(images[0]).read_bytes()]]
        lines = [" ".join(words[i:i + 8]) for i in range(0, len(words), 8)]
        return "Eastbrook University Hospitals NHS Foundation Trust\n" + "\n".join(lines) + "\nPage 1 of 1", "stop"


class RefusalOnceClient(GTClient):
    """Like GTClient, but the first transcribe call (exactly one page, since mini runs
    workers=1 and pages are processed in page_id order) returns a refusal string instead of the
    gt text, to exercise the low-alignment fallback (finding 1)."""

    REFUSAL = ("I am sorry, but I cannot fulfill your request. I am a text-based AI and cannot "
               "process images.")

    def chat_full(self, messages, *, images, temperature, max_tokens, extra=None):
        self.calls += 1
        self.extras.append(extra)
        if self.calls == 1:
            return self.REFUSAL, "stop"
        words = [w["word"] for w in self.by_bytes[Path(images[0]).read_bytes()]]
        lines = [" ".join(words[i:i + 8]) for i in range(0, len(words), 8)]
        return "Eastbrook University Hospitals NHS Foundation Trust\n" + "\n".join(lines) + "\nPage 1 of 1", "stop"


def _stage(settings, protocol, store, client=None):
    return ReadStage(settings, protocol, store, client=client or GTClient(settings, store))


def test_read_version_shape_and_inputs():
    v = read_version("google/medgemma-1.5-4b-it", 1024)
    assert v.startswith("read-") and len(v) == 17
    assert v != read_version("other-model", 1024)
    assert v != read_version("google/medgemma-1.5-4b-it", 2048)


def test_items_follow_pages_partitions(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    assert list(_stage(mini_settings, locked_protocol, mini_pages).items()) == [Batch("b0000")]


def test_run_writes_readings(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    stage = _stage(mini_settings, locked_protocol, mini_pages)
    s = stage.run()
    assert (s.n_in, s.n_out, s.n_quarantined) == (1, 1, 0) and stage.n_fallback == 0
    pages = mini_pages.read("pages")
    r = mini_pages.read("readings")
    assert set(r.page_id) == set(pages.page_id) and len(r) == len(pages)
    assert set(r.columns) >= {
        "page_id", "doc_id", "patient_id", "doc_type", "style", "page_no", "tess_words", "tess_text",
        "medgemma_text", "reading_text", "reader_used", "alignment", "align_frac", "cer_tess",
        "cer_medgemma", "n_gt_words", "read_version", "render_version", "batch_id", "protocol_hash",
    }
    assert (r.read_version == stage.version).all() and (r.render_version == RENDER_VERSION).all()
    assert (r.protocol_hash == locked_protocol.hash).all()
    assert (r.reader_used == "medgemma").all() and (r.reading_text == r.medgemma_text).all()
    assert r.reading_text.str.strip().str.len().gt(0).all()
    for row in r.itertuples():
        tw = json.loads(row.tess_words)
        assert tw and set(tw[0]) == {"word", "conf", "x0", "y0", "x1", "y1"}
        assert row.tess_text == " ".join(w["word"] for w in tw)
        for a in json.loads(row.alignment):
            assert row.reading_text[a["start"]:a["end"]].strip() and a["x0"] < a["x1"] and a["y0"] < a["y1"]
        assert 0.0 <= row.align_frac <= 1.0 and 0.0 <= row.cer_tess <= 1.0 and 0.0 <= row.cer_medgemma <= 1.0
    typed = r[r["style"] == "typed"]
    assert typed.cer_medgemma.median() < 0.02          # stub returns gt text; anchoring must strip the letterhead
    assert typed.cer_tess.median() < 0.10
    assert typed.align_frac.median() > 0.8
    assert (r.n_gt_words == pages.set_index("page_id").loc[r.page_id].gt_words.map(lambda j: len(json.loads(j))).values).all()


def test_second_run_is_noop(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    c = GTClient(mini_settings, mini_pages)
    _stage(mini_settings, locked_protocol, mini_pages, c).run()
    n = c.calls
    part = Path(mini_settings.paths.processed_dir) / "readings" / "b0000.parquet"
    before = part.stat().st_mtime_ns
    s = _stage(mini_settings, locked_protocol, mini_pages, c).run()
    assert s.n_out == 1 and c.calls == n and part.stat().st_mtime_ns == before


def test_stale_render_version_refused_without_force(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    _stage(mini_settings, locked_protocol, mini_pages).run()
    part = Path(mini_settings.paths.processed_dir) / "readings" / "b0000.parquet"
    df = pd.read_parquet(part)
    df["render_version"] = "render-000000000000"
    df.to_parquet(part, index=False)
    with pytest.raises(ValueError, match="--force"):
        _stage(mini_settings, locked_protocol, mini_pages).run()
    s = _stage(mini_settings, locked_protocol, mini_pages).run(force=True)
    assert s.n_out == 1 and (pd.read_parquet(part).render_version == RENDER_VERSION).all()


def test_stale_read_version_refused_without_force(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    _stage(mini_settings, locked_protocol, mini_pages).run()
    part = Path(mini_settings.paths.processed_dir) / "readings" / "b0000.parquet"
    df = pd.read_parquet(part)
    df["read_version"] = "read-000000000000"
    df.to_parquet(part, index=False)
    with pytest.raises(ValueError, match="--force"):
        _stage(mini_settings, locked_protocol, mini_pages).run()


def test_orphan_readings_partition_refused(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    _stage(mini_settings, locked_protocol, mini_pages).run()
    rdir = Path(mini_settings.paths.processed_dir) / "readings"
    (rdir / "b0000.parquet").rename(rdir / "b0042.parquet")
    with pytest.raises(ValueError, match="b0042"):
        _stage(mini_settings, locked_protocol, mini_pages).run()


def test_reader_failing_twice_falls_back_once(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    c = GTClient(mini_settings, mini_pages, fail_times=2)
    stage = _stage(mini_settings, locked_protocol, mini_pages, c)
    s = stage.run()
    assert (s.n_out, s.n_quarantined) == (1, 0) and stage.n_fallback == 1
    r = mini_pages.read("readings").sort_values("page_id")
    fb = r[r.reader_used == "tesseract"]
    assert len(fb) == 1
    row = fb.iloc[0]
    assert row.medgemma_text == "" and row.reading_text == row.tess_text and math.isnan(row.cer_medgemma)
    assert json.loads(row.alignment) and row.align_frac > 0.9    # tess text aligns to itself


def test_reader_failing_once_is_retried(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    c = GTClient(mini_settings, mini_pages, fail_times=1, exc=httpx.ConnectError("down"))
    stage = _stage(mini_settings, locked_protocol, mini_pages, c)
    stage.run()
    assert stage.n_fallback == 0 and (mini_pages.read("readings").reader_used == "medgemma").all()
    assert c.extras[0] is None
    assert c.extras[1] == {"repetition_penalty": RETRY_REPETITION_PENALTY}
    assert all(e is None for e in c.extras[2:])


def test_transport_error_twice_quarantines_batch(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    c = GTClient(mini_settings, mini_pages, fail_times=1000, exc=httpx.ConnectError("down"))
    s = _stage(mini_settings, locked_protocol, mini_pages, c).run()
    assert (s.n_out, s.n_quarantined) == (0, 1)
    q = (Path(mini_settings.paths.processed_dir) / "quarantine" / "read.jsonl").read_text()
    assert "ConnectError" in q
    assert not (Path(mini_settings.paths.processed_dir) / "readings" / "b0000.parquet").exists()


def test_low_alignment_transcript_falls_back(mini_settings, locked_protocol, mini_pages, tessdata_dir):
    c = RefusalOnceClient(mini_settings, mini_pages)
    stage = _stage(mini_settings, locked_protocol, mini_pages, c)
    s = stage.run()
    assert (s.n_out, s.n_quarantined) == (1, 0) and stage.n_fallback == 1
    r = mini_pages.read("readings").sort_values("page_id")
    fb = r[r.reader_used == "tesseract"]
    assert len(fb) == 1
    row = fb.iloc[0]
    assert row.medgemma_text == RefusalOnceClient.REFUSAL
    assert math.isnan(row.cer_medgemma)
    assert row.reading_text == row.tess_text
    assert row.align_frac > 0.9    # tess text aligns to itself


def test_tesseract_failure_quarantines_batch(mini_settings, locked_protocol, mini_pages, tessdata_dir, monkeypatch):
    from auditpace.read import tesseract as tmod

    def boom(self, image_path):
        raise RuntimeError("tesseract exploded")

    monkeypatch.setattr(tmod.Tesseract, "words", boom)
    s = _stage(mini_settings, locked_protocol, mini_pages).run()
    assert (s.n_out, s.n_quarantined) == (0, 1)
    q = (Path(mini_settings.paths.processed_dir) / "quarantine" / "read.jsonl").read_text()
    assert "tesseract exploded" in q
    assert not (Path(mini_settings.paths.processed_dir) / "readings" / "b0000.parquet").exists()


def test_cli_exit_codes(mini_settings, locked_protocol, mini_pages, tessdata_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    proto = str(tmp_path / "protocol.yaml")
    import auditpace.cmd_read as cmd
    monkeypatch.setattr(cmd, "_make_client", lambda s: GTClient(s, mini_pages))
    r = CliRunner().invoke(app, ["read", "--protocol", proto, "--workers", "1"])
    assert r.exit_code == 0, r.output
    assert "read: in=1 out=1 quarantined=0" in r.output and "fallback=0" in r.output
    # tesseract failure on a forced re-run → 1, quarantined
    from auditpace.read import tesseract as tmod

    def boom(self, image_path):
        raise RuntimeError("tesseract exploded")

    monkeypatch.setattr(tmod.Tesseract, "words", boom)
    r = CliRunner().invoke(app, ["read", "--protocol", proto, "--force"])
    assert r.exit_code == 1 and "quarantined" in r.output
    # no pages → 2
    import shutil
    shutil.rmtree(Path(mini_settings.paths.processed_dir) / "pages")
    r = CliRunner().invoke(app, ["read", "--protocol", proto])
    assert r.exit_code == 2 and "pages" in r.output


def test_cli_exit_2_when_endpoint_down(mini_settings, locked_protocol, mini_pages, tessdata_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITPACE_CONFIG", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("AUDITPACE_MOCK", "0")
    monkeypatch.setattr("auditpace.cmd_read.endpoint_serves", lambda ep: False)
    r = CliRunner().invoke(app, ["read", "--protocol", str(tmp_path / "protocol.yaml")])
    assert r.exit_code == 2 and "reader endpoint" in r.output
