"""Stage 8: report → payload.json, prose.json, gateway.log, report.md (+ docs/report.md)."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

from auditpace.models import ClaudeCLI, client_for
from auditpace.report.compare import diff, find_previous, write_payload
from auditpace.report.gateway import GatewayLog, GatewayViolation, Vocab, build_payload
from auditpace.report.prose import (
    ClaudeReporter,
    ProseUnavailable,
    Reporter,
    VLLMReporter,
    ask_model,
    check_prose,
    empty_prose,
    prompt_version,
)
from auditpace.report.render import render_report
from auditpace.stage import Stage

# Fix wave 1 (2026-09-17): 2048 was sized for the toy fixture. On the real 6-criterion cohort
# the compact for_model() prompt is ~8,128 tokens (down from 79,298 pre-fix), leaving ample
# headroom under the reporter's 12,288-token context, but 6 criteria x 3 paragraphs each plus
# the summary/actions_note/caveats_note routinely need more than 2048 completion tokens to
# finish the guided-JSON reply — the real run truncated (finish_reason=length) at 2048 with
# every paragraph still falling back. 3072 leaves 8,128 + 3,072 = 11,200 tokens, 1,088 short of
# the ceiling even on this cohort; ModelClient.cache_key excludes max_tokens, so this does not
# change the recorded fixture's cache key (only prompt_version, which folds it in by design).
MAX_TOKENS = 3072


def code_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5, check=False)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def make_run_id(now: pd.Timestamp, payload_sha: str) -> str:
    return f"rpt-{pd.Timestamp(now).strftime('%Y%m%dT%H%M%S')}-{payload_sha[:8]}"


class ReportStage(Stage):
    name = "report"

    def __init__(self, settings, protocol, store, *, model: str | None, compare_to: str | None, out: Path,
                 now: pd.Timestamp | None = None, run_id: str | None = None, reporter: Reporter | None = None):
        super().__init__(settings, protocol, store)
        self.model, self.compare_to, self.out = model, compare_to, Path(out)
        self.now = now if now is not None else pd.Timestamp.now("UTC").tz_localize(None)
        self.run_id_override = run_id
        self.reporter = reporter
        self.report_dir = self.store.dir / "report"

    def items(self):
        return ["report"]

    def is_done(self, item) -> bool:
        return False

    def _attempt(self, item):
        # One item, no quarantine: a gateway violation or stale table must reach the CLI as exit 2.
        return item, self.process(item), None

    def _make_reporter(self) -> tuple[Reporter | None, str | None, str | None]:
        """(reporter, model tag, prompt_version) — None when --no-model."""
        if self.model is None:
            return None, None, None
        if self.reporter is not None:
            tag = self.settings.models.reporter.model if self.settings.models.reporter else "test-reporter"
            return self.reporter, tag, prompt_version(tag, MAX_TOKENS)
        if self.model == "claude":
            cli = ClaudeCLI(self.settings.synth.model, mock=self.settings.mock, fixtures_dir=self.settings.paths.fixtures_dir)
            return ClaudeReporter(cli), cli.model_tag, prompt_version(cli.model_tag, MAX_TOKENS)
        client = client_for(self.settings, "reporter")
        return VLLMReporter(client, MAX_TOKENS), client.endpoint.model, prompt_version(client.endpoint.model, MAX_TOKENS)

    def process(self, item) -> dict:
        p = self.protocol
        reporter, model_tag, version = self._make_reporter()
        shared_log = GatewayLog([self.report_dir / "gateway.log"])
        provisional_id = self.run_id_override or make_run_id(self.now, "00000000")
        try:
            payload, org_map = build_payload(self.store, p, self.settings, run_id=provisional_id, now=self.now,
                                             code_sha=code_sha(), reporter_model=model_tag, reporter_version=version)
        except GatewayViolation as e:
            shared_log.write("rejected", provisional_id, field=e.field, reason=e.reason)
            raise
        # The run_id suffix is sha256(payload with provisional run_id)[:8] — the payload's identity hash.
        blob = payload.model_dump_json()
        sha = hashlib.sha256(blob.encode()).hexdigest()
        run_id = self.run_id_override or make_run_id(self.now, sha)
        payload = payload.model_copy(update={"run": payload.run.model_copy(update={"run_id": run_id})})
        # The sent line must hash the bytes actually persisted, which include the rewritten run_id.
        blob = payload.model_dump_json()
        sha = hashlib.sha256(blob.encode()).hexdigest()
        run_dir = self.report_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log = GatewayLog([self.report_dir / "gateway.log", run_dir / "gateway.log"])
        log.write("sent", run_id, model=model_tag, prompt_version=version, sha256=sha, n_bytes=len(blob.encode()))
        log.write("payload", run_id, payload=payload.model_dump(mode="json"))
        write_payload(self.report_dir, payload, blob=blob)
        (run_dir / "org_map.json").write_text(json.dumps(org_map, indent=1, sort_keys=True), encoding="utf-8")

        cids = [c.id for c in payload.criteria]
        vocab = Vocab.from_protocol(p, self.store.read("patients"))
        model_note = None
        model_note_detail = None
        rejections = []
        if reporter is None:
            prose = empty_prose(cids)
        else:
            try:
                prose, rejections = check_prose(ask_model(reporter, payload, cids), payload, vocab)
                for r in rejections:
                    log.write("prose_rejected", run_id, section=r.section, tokens=r.tokens, reason=r.reason)
            except ProseUnavailable as e:
                # The raw error (e.g. pydantic's `input_value=...`, a truncated `content[:200]` or
                # `r.stdout[:200]`) is un-back-checked model output — it must never reach report.md.
                # Only a fixed, class-level reason is allowed into model_note/the rendered report;
                # the full text stays in the gateway-log `model_unavailable` line and prose.json's
                # `model_note_detail`.
                model_note = "report writer unavailable (no valid reply after retry)"
                model_note_detail = str(e)
                log.write("model_unavailable", run_id, error=model_note_detail)
                prose = empty_prose(cids)
        (run_dir / "prose.json").write_text(
            json.dumps({"prose": prose.model_dump(), "rejections": [r.model_dump() for r in rejections],
                       "model_note": model_note, "model_note_detail": model_note_detail}, indent=1),
            encoding="utf-8")

        prev, note = find_previous(self.report_dir, p.hash, run_id=self.compare_to, exclude=run_id)
        org_map_changed = False
        if prev is not None:
            prev_map_path = self.report_dir / prev.run.run_id / "org_map.json"
            if prev_map_path.exists():
                try:
                    prev_map = json.loads(prev_map_path.read_text(encoding="utf-8"))
                    org_map_changed = prev_map != org_map
                except (OSError, ValueError):
                    org_map_changed = False
        comparison = diff(prev, payload, org_map_changed=org_map_changed) if prev is not None else None
        md = render_report(payload, prose, comparison, note, rejections, model_note, question=p.question)
        (run_dir / "report.md").write_text(md, encoding="utf-8")
        self.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run_dir / "report.md", self.out)
        model_unavailable = 1 if model_note else 0
        summary = {"run_id": run_id, "sent": 1, "rejected": 0, "prose_rejected": len(rejections),
                   "model": model_tag or "none", "out": str(self.out), "model_note": model_note,
                   "model_unavailable": model_unavailable}
        print(f"report: run_id={run_id} sent=1 rejected=0 prose_rejected={len(rejections)} model={summary['model']} "
              f"model_unavailable={model_unavailable} → {self.out}", flush=True)
        if model_note:
            print(f"report: warning — {model_note}", file=sys.stderr)
        return summary
