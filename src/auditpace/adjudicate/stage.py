"""Stage 5: adjudicate → verdicts (S5 design §7). One item = one S4 readings partition (batch).

Per applicable case the 27B model extracts the verbatim from/to time strings and reason evidence
from the patient's readings; this module parses the times, computes breach vs target (R1),
verifies every quote to page boxes (R3) and writes one verdicts row. Per-case model failures
abstain with `error` set (R5); a transport failure quarantines the batch.

`verdicts` columns: case_id, patient_id, criterion_id, status (breached|not_breached|abstain,
computed), model_status (the model's own call; None when no call), reason_tag (only on breached,
R9), confidence, from_ts, to_ts, hours_documented, evidence (json [{kind, doc_id, page_id, quote,
start, end, bboxes, found, verified}]), rationale, n_docs, error, model, prompt_version,
read_version, batch_id, created_ts, protocol_hash.

`cases` and `documents` are loaded once per run with `Store.read` (pandas) and sliced per batch,
never via `Store.sql`: the DuckDB views are registered only for tables present when the Store was
opened, and both tables are small (cases 1 row per patient x criterion, documents ~6k rows).
The stage never reads `cases.breached` / `cases.true_reason` (those are S6/S8 evaluation only).
"""
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import httpx
import pandas as pd
from pydantic import ValidationError

from auditpace.adjudicate import prompt as P
from auditpace.adjudicate.prompt import DocText, Reply, build_messages, reply_schema
from auditpace.adjudicate.times import TIME_RE, parse_time_quote
from auditpace.adjudicate.verify import MIN_QUOTE_CHARS, VERIFY_RULES, PageReading, verify_evidence
from auditpace.models import ModelJSONError, client_for
from auditpace.protocol import Criterion
from auditpace.stage import Stage

RETRIES = 1
RETRY_NOTE = "\n\nYour previous reply was not valid JSON matching the schema. Return only JSON matching the schema."
PAGE_SEP = "\n\n"

CASE_COLUMNS = ["case_id", "patient_id", "criterion_id", "applies"]
DOC_COLUMNS = ["doc_id", "patient_id", "doc_type", "authored_ts"]
VERDICT_COLUMNS = [
    "case_id", "patient_id", "criterion_id", "status", "model_status", "reason_tag", "confidence",
    "from_ts", "to_ts", "hours_documented", "evidence", "rationale", "n_docs", "error", "model",
    "prompt_version", "read_version", "batch_id", "created_ts",
]


class AdjudicateError(Exception):
    """The model failed to return a valid reply after RETRIES (case abstains with `error`)."""


def prompt_version(model: str, max_tokens: int) -> str:
    template = Criterion(id="X", name="x", type="handoff", **{"from": "a"}, to="b", target_hours=1,
                         standard="s", reasons=["other"])
    h = hashlib.sha256(
        (
            P.SYSTEM_PROMPT + P.USER_TEMPLATE + P.DOC_TEMPLATE + json.dumps(P.EVENT_GLOSS, sort_keys=True)
            + json.dumps(P.REASON_GLOSS, sort_keys=True)
            # sort_keys sorts `properties`; generation order (rationale before status) is captured by `required`
            + json.dumps(reply_schema(template), sort_keys=True) + VERIFY_RULES + TIME_RE.pattern
            + str(MIN_QUOTE_CHARS) + model + str(max_tokens) + str(RETRIES) + RETRY_NOTE
        ).encode()
    )
    return "adj-" + h.hexdigest()[:12]


@dataclass(frozen=True)
class Batch:
    batch_id: str


def _call(client, messages: list[dict], schema: dict, max_tokens: int) -> Reply:
    """One retry on a bad/invalid reply (with RETRY_NOTE appended, which also keys a distinct
    fixture) or on a transport error; then AdjudicateError / re-raise respectively."""
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        msgs = messages if attempt == 0 else messages[:-1] + [
            {"role": "user", "content": messages[-1]["content"] + RETRY_NOTE}]
        try:
            raw = client.chat_json(msgs, json_schema=schema, temperature=0.0, max_tokens=max_tokens)
            return Reply.model_validate(raw)
        except (ModelJSONError, ValidationError) as e:
            last = e
        except httpx.HTTPError:
            if attempt == RETRIES:
                raise
    raise AdjudicateError(f"{type(last).__name__}: {str(last)[:300]}")


def adjudicate_one(client, criterion: Criterion, case_id: str, patient_id: str, docs: list[DocText],
                   pages_by_doc: dict[str, list[PageReading]], max_tokens: int) -> dict:
    """One verdicts row (without the run-level columns). `pages_by_doc` maps doc_id → that
    document's page readings; a quote is only ever searched within the document the model cited."""
    row = {
        "case_id": case_id, "patient_id": patient_id, "criterion_id": criterion.id,
        "status": "abstain", "model_status": None, "reason_tag": None, "confidence": math.nan,
        "from_ts": pd.NaT, "to_ts": pd.NaT, "hours_documented": math.nan,
        "evidence": "[]", "rationale": "", "n_docs": len(docs), "error": None,
    }
    if not docs:
        return row
    try:
        reply = _call(client, build_messages(criterion, docs), reply_schema(criterion), max_tokens)
    except AdjudicateError as e:
        row["error"] = str(e)
        return row
    evidence = []
    for kind, cite in (("from_time", reply.from_time), ("to_time", reply.to_time)):
        if cite is not None:
            evidence.append(verify_evidence(kind, cite.doc_id, cite.quote, pages_by_doc.get(cite.doc_id, [])))
    for cite in reply.evidence:
        evidence.append(verify_evidence("reason", cite.doc_id, cite.quote, pages_by_doc.get(cite.doc_id, [])))
    f = parse_time_quote(reply.from_time.quote) if reply.from_time else None
    t = parse_time_quote(reply.to_time.quote) if reply.to_time else None
    if f is not None and t is not None:
        hours = (t - f) / pd.Timedelta(hours=1)
        # A non-positive gap means the model quoted the same time string for both events (mini: one
        # ED sentence carries the swab time without its date and the reported time with it), so the
        # pair is not evidence of an interval; abstain but keep hours_documented for inspection.
        status = "abstain" if hours <= 0 else ("breached" if hours > criterion.target_hours else "not_breached")
    else:
        hours, status = math.nan, "abstain"
    reason = reply.reason_tag if status == "breached" and reply.reason_tag in criterion.reasons else None
    row.update(
        status=status, model_status=reply.status, reason_tag=reason, confidence=float(reply.confidence),
        from_ts=f if f is not None else pd.NaT, to_ts=t if t is not None else pd.NaT,
        hours_documented=hours, evidence=json.dumps(evidence), rationale=reply.rationale,
    )
    return row


def verdict_frame(rows: list[dict]) -> pd.DataFrame:
    """The verdicts partition frame for `rows` (adjudicate_one rows plus the run-level columns),
    with the dtypes every partition must share regardless of its contents."""
    df = pd.DataFrame(rows, columns=VERDICT_COLUMNS)
    for col in ("from_ts", "to_ts", "created_ts"):
        df[col] = pd.to_datetime(df[col]).astype("datetime64[us]")
    for col in ("model_status", "reason_tag", "error"):
        # Nullable strings. pandas' "string" extension dtype (pd.NA for missing, on both pandas 2.x
        # and 3.x — unlike `astype(str)`, which on 2.x turns None into the text "None") writes an
        # arrow string column with real nulls even when every value is null. An all-None object
        # column would instead be written as arrow type `null`, and DuckDB's glob view over
        # verdicts/*.parquet then fails to cast a later partition's VARCHAR to that NULL type.
        df[col] = df[col].astype(object).where(df[col].notna(), None).astype("string")
    return df


class AdjudicateStage(Stage):
    name = "adjudicate"

    def __init__(self, settings, protocol, store, client=None):
        super().__init__(settings, protocol, store)
        self.client = client if client is not None else client_for(settings, "adjudicator")
        self.model = settings.models.adjudicator.model
        self.max_tokens = settings.adjudicate.max_tokens
        self.version = prompt_version(self.model, self.max_tokens)
        self.criteria = {c.id: c for c in protocol.criteria}
        self.n_errors = 0
        self.n_abstain = 0
        self._cases: pd.DataFrame | None = None
        self._documents: pd.DataFrame | None = None

    def _read_part(self, batch_id: str) -> Path:
        return self.store.part_dir("readings") / f"{batch_id}.parquet"

    def _verdict_part(self, batch_id: str) -> Path:
        return self.store.part_dir("verdicts") / f"{batch_id}.parquet"

    def _load_tables(self) -> None:
        """`cases` and `documents` once per run (pandas, not SQL — see module docstring)."""
        self._cases = self.store.read("cases")[CASE_COLUMNS]
        try:
            self._documents = self.store.read("documents")[DOC_COLUMNS]
        except FileNotFoundError:   # nothing synthesised yet: every case abstains with n_docs=0
            self._documents = pd.DataFrame(columns=DOC_COLUMNS)

    def items(self):
        for p in sorted(self.store.part_dir("readings").glob("*.parquet")):
            yield Batch(p.stem)

    def _expected(self, batch_id: str) -> pd.DataFrame:
        """Applicable cases for the batch's patients, with each patient's read_version."""
        if self._cases is None:
            self._load_tables()
        rd = pd.read_parquet(self._read_part(batch_id), columns=["patient_id", "read_version"])
        rv = rd.drop_duplicates("patient_id").set_index("patient_id").read_version
        c = self._cases
        cases = (c[c.applies.astype(bool) & c.patient_id.isin(rv.index)]
                 [["case_id", "patient_id", "criterion_id"]].sort_values("case_id").reset_index(drop=True))
        cases["read_version"] = cases.patient_id.map(rv)
        return cases

    def _current(self, batch_id: str) -> bool:
        """True when the verdicts partition exists, covers exactly the applicable cases of the
        readings partition's patients, was produced by this prompt_version and protocol_hash, and
        every row's read_version matches its patient's."""
        part = self._verdict_part(batch_id)
        if not part.exists() or not self._read_part(batch_id).exists():
            return False
        have = pd.read_parquet(part, columns=["case_id", "prompt_version", "read_version", "protocol_hash"])
        want = self._expected(batch_id)
        if set(have.case_id) != set(want.case_id) or len(have) != len(want):
            return False
        if not (have.prompt_version == self.version).all():
            return False
        if not (have.protocol_hash == self.protocol.hash).all():
            return False
        w = want.set_index("case_id").read_version
        return bool((have.read_version.values == w.loc[have.case_id].values).all())

    def is_done(self, batch: Batch) -> bool:
        return self._current(batch.batch_id)

    def run(self, limit: int | None = None, force: bool = False, workers: int = 1):
        """Refuse stale verdicts partitions (missing readings batch, case_id mismatch, stale
        read_version, stale protocol_hash, or old prompt_version) unless `force`, which deletes
        them first."""
        self._load_tables()
        vdir = self.store.part_dir("verdicts")
        stale = [p.stem for p in sorted(vdir.glob("*.parquet"))] if vdir.exists() else []
        stale = [s for s in stale if not self._current(s)]
        if stale:
            if not force:
                raise ValueError(
                    f"verdicts/ has stale partitions {stale} (missing readings batch, case_id mismatch, "
                    f"stale read_version, stale protocol_hash, or prompt_version != {self.version}); "
                    f"rerun with --force"
                )
            for stem in stale:
                (vdir / f"{stem}.parquet").unlink()
        self.n_errors = self.n_abstain = 0
        summary = super().run(limit=limit, force=force, workers=workers)
        self.n_errors = sum(o["errors"] for o in self.outputs)
        self.n_abstain = sum(o["abstain"] for o in self.outputs)
        print(f"adjudicate: errors={self.n_errors} abstain={self.n_abstain}", flush=True)
        return summary

    def _patient_docs(self, readings: pd.DataFrame, docs: pd.DataFrame, pid: str
                      ) -> tuple[list[DocText], dict[str, list[PageReading]]]:
        pages_by_doc: dict[str, list[PageReading]] = {}
        for r in readings[readings.patient_id == pid].sort_values(["doc_id", "page_no"]).itertuples(index=False):
            pages_by_doc.setdefault(r.doc_id, []).append(
                PageReading(r.page_id, int(r.page_no), r.reading_text, json.loads(r.alignment)))
        texts = []
        for d in docs[docs.patient_id == pid].itertuples(index=False):
            pages = pages_by_doc.get(d.doc_id)
            if not pages:
                continue   # document without readings (partial upstream run) is not shown
            texts.append(DocText(d.doc_id, d.doc_type, pd.Timestamp(d.authored_ts),
                                 PAGE_SEP.join(p.reading_text for p in pages)))
        return texts, pages_by_doc

    def process(self, batch: Batch) -> dict:
        readings = pd.read_parquet(self._read_part(batch.batch_id))
        cases = self._expected(batch.batch_id)
        docs = self._documents[self._documents.patient_id.isin(cases.patient_id.unique())]
        cache: dict[str, tuple[list[DocText], dict[str, list[PageReading]]]] = {}
        rows, errors, abstain = [], 0, 0
        now = pd.Timestamp.now("UTC").tz_localize(None)
        for c in cases.itertuples(index=False):
            if c.patient_id not in cache:
                cache[c.patient_id] = self._patient_docs(readings, docs, c.patient_id)
            texts, pages_by_doc = cache[c.patient_id]
            row = adjudicate_one(self.client, self.criteria[c.criterion_id], c.case_id, c.patient_id,
                                 texts, pages_by_doc, self.max_tokens)
            errors += row["error"] is not None
            abstain += row["status"] == "abstain"
            row.update(model=self.model, prompt_version=self.version, read_version=c.read_version,
                       batch_id=batch.batch_id, created_ts=now)
            rows.append(row)
        df = verdict_frame(rows)
        self.store.write_part("verdicts", batch.batch_id, df, self.protocol.hash)
        print(f"adjudicate: {batch.batch_id} ok, {len(df)} cases, {errors} errors, {abstain} abstain", flush=True)
        return {"cases": len(df), "errors": errors, "abstain": abstain}
