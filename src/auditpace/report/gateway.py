"""The gateway: the only thing that crosses to the report writer is a Payload, an allowlist by
construction (spec §3). Every string is closed by a vocabulary built from the protocol and the
observed segment values; organisations are pseudonymised; nothing free-text exists here."""
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from auditpace.estimate.categorise import reason_class_of
from auditpace.estimate.reviews import empty_reviews, latest_reviews
from auditpace.protocol import Protocol
from auditpace.settings import Settings
from auditpace.store import Store
from auditpace.workbench.render import (
    NO_DISCREPANCY_TEXT,
    PROVISIONAL_MIN_REVIEWS,
    provisional_reason,
)

ORG_RE = re.compile(r"^Org-\d{2,}$")
SEG_VALUE_RE = re.compile(r"^[A-Za-z0-9 _/+-]{1,30}$")          # "80+" is an age band
WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")
HASH_RE = re.compile(r"^[0-9a-f]{12,64}$")
VERSION_RE = re.compile(r"^(adj|read|rpt)-[0-9a-z]{4,12}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._/:-]{1,64}$")
SHA_RE = re.compile(r"^([0-9a-f]{7,40}|unknown)$")
RUN_ID_RE = re.compile(r"^rpt-\d{8}T\d{6}-[0-9a-f]{8}$")
REVIEWER_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")
# A dashed UUID or a raw 32-hex id — the shape of a case_id/patient_id. code_sha and the model
# fields have no protocol vocabulary to check membership against (they're operational, not
# protocol-derived), so this is the only guard against a leaked identifier landing there.
LEAKED_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}")

Method = Literal["naive", "ppi", "classical"]
Flag = Literal["n_reviewed_insufficient", "no_discrepancy_observed"]
Signal = Literal["none", "alert_low", "alert_high", "alarm_low", "alarm_high", "below_target", "rank_1"]
AlertKind = Literal["org_outlier", "org_exemplar", "criterion_below_target", "week_outlier", "top_time_lost"]
Klass = Literal["system", "legitimate", "undetermined"]


class GatewayViolation(ValueError):
    def __init__(self, field: str, reason: str):
        super().__init__(f"{field}: {reason}")
        self.field, self.reason = field, reason


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rate(_Strict):
    rate: float | None
    lo: float | None
    hi: float | None


class Period(_Strict):
    start: str = Field(pattern=DATE_RE.pattern)
    end: str = Field(pattern=DATE_RE.pattern)


class ModelMeta(_Strict):
    model: str | None = Field(default=None, pattern=MODEL_RE.pattern)
    prompt_version: str | None = Field(default=None, pattern=VERSION_RE.pattern)


class ReaderMeta(_Strict):
    read_version: str = Field(pattern=VERSION_RE.pattern)


class ReviewMeta(_Strict):
    estimation_pool_fraction: float
    confidence: float


class RunMeta(_Strict):
    run_id: str = Field(pattern=RUN_ID_RE.pattern)
    protocol_id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    protocol_hash: str = Field(pattern=HASH_RE.pattern)
    code_sha: str = Field(pattern=SHA_RE.pattern)
    period: Period | None
    cohort_n: int
    generated_ts: str = Field(pattern=TS_RE.pattern)
    adjudicator: ModelMeta
    reader: ReaderMeta
    reporter: ModelMeta
    review: ReviewMeta
    suppress_below: int
    estimates_computed_ts: str = Field(pattern=TS_RE.pattern)


class CompletenessRow(_Strict):
    event: str
    n_with: int
    n_without: int


class ReasonRow(_Strict):
    code: str
    klass: Klass
    action: str
    n: int
    rate: float | None
    lo: float | None
    hi: float | None


class SegmentRow(_Strict):
    key: str
    value: str
    n: int
    corrected: Rate
    method: Method
    suppressed: bool


class FunnelRow(_Strict):
    org: str
    n: int
    rate: float | None
    lo: float | None
    hi: float | None
    signal: Signal


class WeekSignal(_Strict):
    week: str = Field(pattern=WEEK_RE.pattern)
    signal: Signal


class LatestWeek(_Strict):
    week: str = Field(pattern=WEEK_RE.pattern)
    rate: float | None
    lo: float | None
    hi: float | None


class Runchart(_Strict):
    n_weeks: int
    latest: LatestWeek | None
    signals: list[WeekSignal]


class Timelost(_Strict):
    hours_lost: float | None
    median_excess_h: float | None
    rank: int | None


class CriterionReport(_Strict):
    id: str
    name: str
    from_event: str
    to_event: str
    target_hours: float
    standard: str
    owner: str
    compliance_target: float | None
    n: int
    n_reviewed: int
    n_abstain: int
    n_no_end: int
    n_breached_system: int
    n_breached_legitimate: int
    n_breached_undetermined: int
    naive: Rate
    corrected: Rate
    method: Method
    flag: Flag | None
    provisional_reason: str | None
    rate_system: Rate
    rate_legitimate: Rate
    rate_undetermined: Rate
    reasons: list[ReasonRow]
    segments: list[SegmentRow]
    funnel: list[FunnelRow]
    runchart: Runchart
    timelost: Timelost


class AlertRow(_Strict):
    alert_id: str
    kind: AlertKind
    criterion_id: str
    segment_key: str
    segment_value: str
    signal: Signal
    rate: float | None
    lo: float | None
    hi: float | None
    n: int
    n_reviewed: int
    method: Method
    hours_lost: float | None
    dominant_reason: str | None
    action: str
    owner: str


class ReviewsQuality(_Strict):
    n_latest: int
    n_validated: int
    n_disputed: int
    n_flagged: int
    n_estimation_pool: int
    reviewers: list[str]


class Quality(_Strict):
    n_cases: int
    n_abstain: int
    n_no_end: int
    abstain_rate: float
    no_end_rate: float
    n_cites: int
    n_unverified_cites: int
    unverified_cite_rate: float
    quarantined: dict[str, int]
    n_suppressed_cells: int
    reviews: ReviewsQuality


class CoverageRow(_Strict):
    criterion_id: str
    fraction: float
    method: Literal["naive", "corrected"]
    coverage: float
    mean_width: float


class KappaRow(_Strict):
    criterion_id: str
    kappa: float | None
    n: int


class AccuracyRow(_Strict):
    criterion_id: str
    acc: float | None
    n: int


class Validation(_Strict):
    present: Literal[True] = True
    coverage: list[CoverageRow]
    kappa: list[KappaRow]
    reason_accuracy: list[AccuracyRow]


VOLATILE_RUN_FIELDS = ("run_id", "generated_ts", "code_sha", "estimates_computed_ts")


class Payload(_Strict):
    payload_version: Literal[1] = 1
    run: RunMeta
    completeness: list[CompletenessRow]
    criteria: list[CriterionReport]
    alerts: list[AlertRow]
    quality: Quality
    validation: Validation | None

    def for_model(self) -> dict:
        """What the reporter sees: a compact, pre-formatted view (spec §5, fix wave 1) — not the full
        payload. `run_id`/`generated_ts`/`code_sha`/`estimates_computed_ts`/`reporter.*` are dropped
        (they change on every run and carry nothing the prose needs); `validation` is dropped (not
        audited-aggregate content the report writer should see); organisation *segment* rows are
        dropped (there can be dozens per criterion — the org signal that matters is already isolated
        in `funnel`, rows with signal != "none"), and suppressed segments are dropped. Every rate,
        hours and count figure is rendered through `fmt.pct/ci/hours/num` — the exact strings the
        template prints — so a model that copies a figure verbatim always passes `check_prose`
        (which computes its printed-token set from the full `Payload`, independent of this view).
        The import is local: `fmt` imports `Payload` from this module, so a top-level import here
        would cycle; by the time `for_model` runs both modules are already loaded."""
        from auditpace.report.fmt import ci, hours, num, pct

        def rate_ci(r) -> str:
            return f"{pct(r.rate)} % ({ci(r.lo, r.hi)} %)"

        def rate_pct(r) -> str:
            return f"{pct(r.rate)} %"

        r = self.run
        run = {
            "protocol_id": r.protocol_id,
            "protocol_hash": r.protocol_hash,
            "period": f"{r.period.start} to {r.period.end}" if r.period else "not set",
            "cohort_n": r.cohort_n,
            "adjudicator_model": r.adjudicator.model,
            "adjudicator_prompt_version": r.adjudicator.prompt_version,
            "review_pool_fraction": r.review.estimation_pool_fraction,
            "confidence_pct": str(round(100 * r.review.confidence)),
            "suppress_below": r.suppress_below,
        }
        completeness = [{"event": c.event, "with": c.n_with, "without": c.n_without} for c in self.completeness]

        criteria = []
        for c in self.criteria:
            reasons = [{"code": rr.code, "class": rr.klass, "n": rr.n, "rate": rate_ci(rr), "action": rr.action}
                      for rr in c.reasons]
            segments = [{"key": s.key, "value": s.value, "n": s.n, "rate": rate_ci(s.corrected)}
                       for s in c.segments if s.key != "organization" and not s.suppressed]
            outliers = [f"{f.org} {f.signal} {pct(f.rate)} % ({ci(f.lo, f.hi)} %), n = {f.n}" for f in c.funnel]
            latest = None
            if c.runchart.latest is not None:
                lw = c.runchart.latest
                latest = f"{lw.week} {pct(lw.rate)} % ({ci(lw.lo, lw.hi)} %)"
            runchart = {"n_weeks": c.runchart.n_weeks, "latest": latest,
                       "signals": [f"{w.week} {w.signal}" for w in c.runchart.signals]}
            criteria.append({
                "id": c.id, "name": c.name, "handoff": f"{c.from_event} → {c.to_event}",
                "target_hours": hours(c.target_hours), "standard": c.standard, "owner": c.owner,
                "compliance_target_pct": None if c.compliance_target is None else pct(c.compliance_target),
                "n": c.n, "n_reviewed": c.n_reviewed, "n_abstain": c.n_abstain, "n_no_end": c.n_no_end,
                "n_breached_system": c.n_breached_system, "n_breached_legitimate": c.n_breached_legitimate,
                "n_breached_undetermined": c.n_breached_undetermined,
                "corrected": rate_ci(c.corrected), "naive": rate_ci(c.naive), "method": c.method,
                "provisional_reason": c.provisional_reason,
                "breach_rates": {"system": rate_pct(c.rate_system), "legitimate": rate_pct(c.rate_legitimate),
                                "undetermined": rate_pct(c.rate_undetermined)},
                "reasons": reasons, "segments": segments, "organisation_outliers": outliers,
                "runchart": runchart, "hours_lost": hours(c.timelost.hours_lost),
                "median_excess_h": hours(c.timelost.median_excess_h), "rank": num(c.timelost.rank),
            })

        alerts = [{"kind": a.kind, "criterion_id": a.criterion_id, "where": f"{a.segment_key} = {a.segment_value}",
                  "signal": a.signal, "rate": rate_ci(a), "n": a.n, "n_reviewed": a.n_reviewed, "method": a.method,
                  "hours_lost": hours(a.hours_lost), "dominant_reason": a.dominant_reason, "action": a.action,
                  "owner": a.owner} for a in self.alerts]

        q = self.quality
        quality = {"n_cases": q.n_cases, "n_abstain": q.n_abstain, "n_no_end": q.n_no_end,
                  "abstain_rate": f"{pct(q.abstain_rate)} %", "no_end_rate": f"{pct(q.no_end_rate)} %",
                  "n_cites": q.n_cites, "n_unverified_cites": q.n_unverified_cites,
                  "unverified_cite_rate": f"{pct(q.unverified_cite_rate)} %", "n_suppressed_cells": q.n_suppressed_cells,
                  "quarantined": dict(q.quarantined),
                  "reviews": {"n_latest": q.reviews.n_latest, "n_validated": q.reviews.n_validated,
                             "n_disputed": q.reviews.n_disputed, "n_flagged": q.reviews.n_flagged,
                             "n_estimation_pool": q.reviews.n_estimation_pool, "reviewers": list(q.reviews.reviewers)}}

        return {"run": run, "completeness": completeness, "criteria": criteria, "alerts": alerts, "quality": quality}


@dataclass(frozen=True)
class Vocab:
    criterion_ids: frozenset[str]
    names: dict[str, str]
    standards: dict[str, str]
    from_events: dict[str, str]
    to_events: dict[str, str]
    events: frozenset[str]
    reasons: dict[str, frozenset[str]]          # per criterion, taxonomy + "undetermined"
    owners: frozenset[str]
    actions: frozenset[str]
    segment_keys: frozenset[str]
    segment_values: dict[str, frozenset[str]]  # observed, per key, organization excluded (pseudonymised)
    provisional_texts: frozenset[str]
    protocol_id: str
    protocol_hash: str | None

    @classmethod
    def from_protocol(cls, protocol: Protocol, patients: pd.DataFrame) -> "Vocab":
        crits = protocol.criteria
        owners, actions = set(), set()
        for c in crits:
            owners.add(protocol.owner(c.id))
            for r in c.reasons:
                actions.add(protocol.action(c.id, r))
        seg_values = {}
        for key in protocol.segments:
            if key == "organization":
                continue
            col = key if key in patients.columns else None
            vals = patients[col].dropna().astype(str).unique() if col else []
            seg_values[key] = frozenset(v for v in vals if SEG_VALUE_RE.match(v))
        return cls(
            criterion_ids=frozenset(c.id for c in crits),
            names={c.id: c.name for c in crits},
            standards={c.id: c.standard for c in crits},
            from_events={c.id: c.from_ for c in crits},
            to_events={c.id: c.to for c in crits},
            events=frozenset(protocol.events),
            reasons={c.id: frozenset([*c.reasons, "undetermined"]) for c in crits},
            owners=frozenset(owners),
            actions=frozenset(actions),
            segment_keys=frozenset(protocol.segments),
            segment_values=seg_values,
            provisional_texts=frozenset({"fewer than 2 reviews", NO_DISCREPANCY_TEXT,
                                         f"fewer than {PROVISIONAL_MIN_REVIEWS} reviews"}),
            protocol_id=protocol.protocol_id,
            protocol_hash=protocol.hash,
        )


def _org_or_literal(value: str) -> bool:
    return value in ("all", "unknown") or bool(ORG_RE.match(value))


def _no_id_leak(value: str) -> bool:
    return not LEAKED_ID_RE.search(value)


def _segment_value_ok(vocab: Vocab, key: str, value: str) -> bool:
    if key == "organization":
        return _org_or_literal(value)
    if key == "all":
        return value == "all"
    if key == "week":
        return bool(WEEK_RE.match(value))
    return value in vocab.segment_values.get(key, frozenset())


def _check_vocab(p: Payload, vocab: Vocab) -> None:
    def need(cond: bool, field: str, reason: str) -> None:
        if not cond:
            raise GatewayViolation(field, reason)

    need(p.run.protocol_id == vocab.protocol_id, "run.protocol_id", "not the protocol's id")
    need(p.run.protocol_hash == vocab.protocol_hash, "run.protocol_hash", "not the protocol's hash")
    need(_no_id_leak(p.run.code_sha), "run.code_sha", "looks like a leaked id")
    need(p.run.adjudicator.model is None or _no_id_leak(p.run.adjudicator.model),
         "run.adjudicator.model", "looks like a leaked id")
    need(p.run.reporter.model is None or _no_id_leak(p.run.reporter.model),
         "run.reporter.model", "looks like a leaked id")
    for i, row in enumerate(p.completeness):
        need(row.event in vocab.events, f"completeness[{i}].event", f"unknown event {row.event!r}")
    for i, c in enumerate(p.criteria):
        f = f"criteria[{i}]"
        need(c.id in vocab.criterion_ids, f"{f}.id", f"unknown criterion {c.id!r}")
        need(c.name == vocab.names[c.id], f"{f}.name", "not the protocol's name")
        need(c.standard == vocab.standards[c.id], f"{f}.standard", "not the protocol's standard")
        need(c.from_event == vocab.from_events[c.id], f"{f}.from_event", "not the protocol's event")
        need(c.to_event == vocab.to_events[c.id], f"{f}.to_event", "not the protocol's event")
        need(c.owner in vocab.owners, f"{f}.owner", "not a protocol owner")
        need(c.provisional_reason is None or c.provisional_reason in vocab.provisional_texts,
             f"{f}.provisional_reason", "not the workbench wording")
        for j, r in enumerate(c.reasons):
            need(r.code in vocab.reasons[c.id], f"{f}.reasons[{j}].code", f"not in {c.id} taxonomy")
            need(r.action in vocab.actions, f"{f}.reasons[{j}].action", "not a protocol action")
        for j, s in enumerate(c.segments):
            need(s.key in vocab.segment_keys, f"{f}.segments[{j}].key", "not a protocol segment")
            need(_segment_value_ok(vocab, s.key, s.value), f"{f}.segments[{j}].value", "not an allowed segment value")
        for j, fr in enumerate(c.funnel):
            need(_org_or_literal(fr.org), f"{f}.funnel[{j}].org", "not a pseudonymised organisation")
    for i, a in enumerate(p.alerts):
        f = f"alerts[{i}]"
        need(a.criterion_id in vocab.criterion_ids, f"{f}.criterion_id", "unknown criterion")
        need(a.segment_key in vocab.segment_keys | {"all", "week"}, f"{f}.segment_key", "not a segment key")
        need(_segment_value_ok(vocab, a.segment_key, a.segment_value), f"{f}.segment_value", "not an allowed value")
        need(a.alert_id == f"{a.kind}:{a.criterion_id}:{a.segment_value}", f"{f}.alert_id", "not kind:criterion:value")
        need(a.dominant_reason is None or a.dominant_reason in vocab.reasons[a.criterion_id],
             f"{f}.dominant_reason", "not in taxonomy")
        need(a.action in vocab.actions, f"{f}.action", "not a protocol action")
        need(a.owner in vocab.owners, f"{f}.owner", "not a protocol owner")
    for i, r in enumerate(p.quality.reviews.reviewers):
        need(bool(REVIEWER_RE.match(r)), f"quality.reviews.reviewers[{i}]", "reviewer name outside [a-z0-9_-]")
    for stage in p.quality.quarantined:
        need(re.fullmatch(r"[a-z_]{1,20}", stage) is not None, "quality.quarantined", "stage name")
    if p.validation:
        for i, row in enumerate(p.validation.coverage):
            need(row.criterion_id in vocab.criterion_ids, f"validation.coverage[{i}].criterion_id", "unknown criterion")
        for i, row in enumerate(p.validation.kappa):
            need(row.criterion_id in vocab.criterion_ids, f"validation.kappa[{i}].criterion_id", "unknown criterion")
        for i, row in enumerate(p.validation.reason_accuracy):
            need(row.criterion_id in vocab.criterion_ids, f"validation.reason_accuracy[{i}].criterion_id",
                 "unknown criterion")


def validate_payload(data: dict, vocab: Vocab) -> Payload:
    """Structural check (types, patterns, no extra fields) then vocabulary check. Any failure is a
    GatewayViolation naming the field: the run stops, nothing is dropped silently."""
    try:
        p = Payload.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first["loc"])
        raise GatewayViolation(loc, first["msg"]) from e
    _check_vocab(p, vocab)
    return p


def nan_to_none(x):
    """NaN/NA -> None, a numpy/pandas scalar -> its Python value, everything else unchanged."""
    if hasattr(x, "item"):
        x = x.item()
    if x is None or x is pd.NA:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return x


def _rate(row, prefix: str) -> dict:
    return {"rate": nan_to_none(row[f"{prefix}_rate"]), "lo": nan_to_none(row[f"{prefix}_lo"]),
            "hi": nan_to_none(row[f"{prefix}_hi"])}


def _rate_cls(row, cls: str) -> dict:
    """rate_{system,legitimate,undetermined} columns: unlike naive_/corrected_, the rate itself has
    no `_rate` suffix (`build_estimates` writes `rate_{cls}`, `rate_{cls}_lo`, `rate_{cls}_hi`)."""
    return {"rate": nan_to_none(row[f"rate_{cls}"]), "lo": nan_to_none(row[f"rate_{cls}_lo"]),
            "hi": nan_to_none(row[f"rate_{cls}_hi"])}


def _ts(x) -> str:
    return pd.Timestamp(x).strftime("%Y-%m-%dT%H:%M:%S")


def org_pseudonyms(patients: pd.DataFrame) -> dict[str, str]:
    """uuid -> Org-nn, ranked by patient count desc then id; `unknown` is not an organisation."""
    counts = patients.organization_id.dropna().astype(str)
    counts = counts[counts != "unknown"].value_counts()
    ordered = sorted(counts.index, key=lambda o: (-int(counts[o]), o))
    return {o: f"Org-{i + 1:02d}" for i, o in enumerate(ordered)}


def _pseud(mapping: dict[str, str], value) -> str:
    v = str(value)
    return v if v in ("all", "unknown") else mapping.get(v, v)  # an unmapped uuid fails validation downstream


def _read_meta(store: Store) -> dict:
    v = store.read("verdicts")
    ev = v.evidence.map(json.loads)
    n_cites = int(ev.map(len).sum())
    n_unv = int(ev.map(lambda es: sum(1 for e in es if not e.get("verified"))).sum())
    return {"model": str(v.model.iloc[0]), "prompt_version": str(v.prompt_version.iloc[0]),
            "read_version": str(v.read_version.iloc[0]), "n_cites": n_cites, "n_unverified": n_unv}


def _quarantine_counts(store: Store) -> dict[str, int]:
    qdir = store.dir / "quarantine"
    out = {}
    for f in sorted(qdir.glob("*.jsonl")) if qdir.exists() else []:
        out[f.stem] = sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
    return out


def _reviews_quality(store: Store, protocol: Protocol) -> dict:
    rv = store.read("reviews") if store.exists("reviews") else empty_reviews()
    if len(rv) == 0:
        return {"n_latest": 0, "n_validated": 0, "n_disputed": 0, "n_flagged": 0, "n_estimation_pool": 0, "reviewers": []}
    lr = latest_reviews(rv)
    counts = lr.validation_state.value_counts()
    live = lr[lr.validation_state != "flagged"]
    # n_latest: every case with a latest review, whatever its state; n_flagged/n_validated/n_disputed
    # are how those latest reviews break down (they sum to n_latest). n_estimation_pool is restricted
    # to live (non-flagged) reviews since a flagged one has no usable pool assignment for correction.
    return {"n_latest": len(lr), "n_validated": int(counts.get("validated", 0)),
            "n_disputed": int(counts.get("disputed", 0)), "n_flagged": int(counts.get("flagged", 0)),
            "n_estimation_pool": int((live.pool == "estimation").sum()),
            "reviewers": sorted(set(rv.reviewer.astype(str)))}


def build_payload(store: Store, protocol: Protocol, settings: Settings, *, run_id: str, now: pd.Timestamp,
                  code_sha: str, reporter_model: str | None, reporter_version: str | None) -> tuple[Payload, dict[str, str]]:
    """Read S6's tables and the verdict metadata into a validated Payload. Returns the payload and the
    organisation map {pseudonym: uuid}, which is written next to the payload but never inside it."""
    patients = store.read("patients")
    vocab = Vocab.from_protocol(protocol, patients)
    est = store.read("estimates")
    alerts = store.read("alerts")
    funnel = store.read("funnel")
    runchart = store.read("runchart")
    timelost = store.read("timelost")
    comp = store.read("cohort_completeness")
    meta = _read_meta(store)
    orgs = org_pseudonyms(patients)

    criteria = []
    for c in protocol.criteria:
        allrow = est[(est.criterion_id == c.id) & (est.segment_key == "all")]
        if allrow.empty:
            continue
        a = allrow.iloc[0]
        rb = json.loads(a.reason_breakdown) if isinstance(a.reason_breakdown, str) else {}
        reasons = []
        for code in [*c.reasons, "undetermined"]:
            r = rb.get(code, {})
            klass = "undetermined" if code == "undetermined" else reason_class_of(protocol, c.id, "breached", code)
            reasons.append({"code": code, "klass": klass, "action": protocol.action(c.id, None if code == "undetermined" else code),
                            "n": int(r.get("n", 0)), "rate": nan_to_none(r.get("rate")), "lo": nan_to_none(r.get("lo")),
                            "hi": nan_to_none(r.get("hi"))})
        segs = []
        for _, s in est[(est.criterion_id == c.id) & (est.segment_key != "all")].iterrows():
            segs.append({"key": s.segment_key, "value": _pseud(orgs, s.segment_value), "n": int(s.n),
                         "corrected": _rate(s, "corrected"), "method": s.method, "suppressed": bool(s.suppressed)})
        fn = funnel[(funnel.criterion_id == c.id) & (funnel.signal != "none")]
        fun = [{"org": _pseud(orgs, f.organization_id), "n": int(f.n), "rate": nan_to_none(f.rate),
                "lo": nan_to_none(f.lo), "hi": nan_to_none(f.hi), "signal": f.signal} for f in fn.itertuples()]
        rc = runchart[runchart.criterion_id == c.id].sort_values("week")
        latest = rc[rc.latest] if "latest" in rc.columns else rc.tail(1)
        run = {"n_weeks": len(rc),
               "latest": None if latest.empty else {"week": str(latest.iloc[0].week), "rate": nan_to_none(latest.iloc[0].rate),
                                                    "lo": nan_to_none(latest.iloc[0].lo), "hi": nan_to_none(latest.iloc[0].hi)},
               "signals": [{"week": str(w.week), "signal": w.signal} for w in rc[rc.signal != "none"].itertuples()]}
        tl = timelost[(timelost.criterion_id == c.id) & (timelost.organization_id == "all")]
        t = tl.iloc[0] if len(tl) else None
        criteria.append({
            "id": c.id, "name": c.name, "from_event": c.from_, "to_event": c.to, "target_hours": float(c.target_hours),
            "standard": c.standard, "owner": protocol.owner(c.id), "compliance_target": protocol.compliance_target(c.id),
            "n": int(a.n), "n_reviewed": int(a.n_reviewed), "n_abstain": int(a.n_abstain), "n_no_end": int(a.n_no_end),
            "n_breached_system": int(a.n_breached_system), "n_breached_legitimate": int(a.n_breached_legitimate),
            "n_breached_undetermined": int(a.n_breached_undetermined),
            "naive": _rate(a, "naive"), "corrected": _rate(a, "corrected"), "method": a.method,
            "flag": nan_to_none(a.flag), "provisional_reason": provisional_reason(int(a.n_reviewed), nan_to_none(a.flag)),
            "rate_system": _rate_cls(a, "system"), "rate_legitimate": _rate_cls(a, "legitimate"),
            "rate_undetermined": _rate_cls(a, "undetermined"),
            "reasons": reasons, "segments": segs, "funnel": fun, "runchart": run,
            "timelost": {"hours_lost": nan_to_none(t.hours_lost) if t is not None else None,
                         "median_excess_h": nan_to_none(t.median_excess_h) if t is not None else None,
                         # t["rank"] not t.rank: "rank" collides with Series.rank(), the pandas method
                         "rank": None if t is None or nan_to_none(t["rank"]) is None else int(t["rank"])},
        })

    alert_rows = []
    for al in alerts.itertuples():
        value = _pseud(orgs, al.segment_value)
        alert_rows.append({"alert_id": f"{al.kind}:{al.criterion_id}:{value}", "kind": al.kind, "criterion_id": al.criterion_id,
                           "segment_key": al.segment_key, "segment_value": value, "signal": al.signal,
                           "rate": nan_to_none(al.rate), "lo": nan_to_none(al.lo), "hi": nan_to_none(al.hi), "n": int(al.n),
                           "n_reviewed": int(al.n_reviewed), "method": al.method, "hours_lost": nan_to_none(al.hours_lost),
                           "dominant_reason": nan_to_none(al.dominant_reason), "action": al.action, "owner": al.owner})

    allrows = est[est.segment_key == "all"]
    n_cases = int(allrows.n.sum() + allrows.n_abstain.sum() + allrows.n_no_end.sum()) if len(allrows) else 0
    n_abstain, n_no_end = int(allrows.n_abstain.sum()), int(allrows.n_no_end.sum())
    quality = {"n_cases": n_cases, "n_abstain": n_abstain, "n_no_end": n_no_end,
               "abstain_rate": n_abstain / n_cases if n_cases else 0.0, "no_end_rate": n_no_end / n_cases if n_cases else 0.0,
               "n_cites": meta["n_cites"], "n_unverified_cites": meta["n_unverified"],
               "unverified_cite_rate": meta["n_unverified"] / meta["n_cites"] if meta["n_cites"] else 0.0,
               "quarantined": _quarantine_counts(store), "n_suppressed_cells": int(est.suppressed.sum()),
               "reviews": _reviews_quality(store, protocol)}

    period = ({"start": str(protocol.cohort.period["start"]), "end": str(protocol.cohort.period["end"])}
              if protocol.cohort.period else None)
    data = {
        "payload_version": 1,
        "run": {"run_id": run_id, "protocol_id": protocol.protocol_id, "protocol_hash": protocol.hash, "code_sha": code_sha,
                "period": period,
                "cohort_n": int(patients.patient_id.nunique()), "generated_ts": _ts(now),
                "adjudicator": {"model": meta["model"], "prompt_version": meta["prompt_version"]},
                "reader": {"read_version": meta["read_version"]},
                "reporter": {"model": reporter_model, "prompt_version": reporter_version},
                "review": {"estimation_pool_fraction": protocol.review.estimation_pool_fraction,
                           "confidence": protocol.review.confidence},
                "suppress_below": protocol.suppress_below, "estimates_computed_ts": _ts(est.computed_ts.iloc[0])},
        "completeness": [{"event": r.event_type, "n_with": int(r.n_patients_with), "n_without": int(r.n_patients_without)}
                         for r in comp.itertuples()],
        "criteria": criteria, "alerts": alert_rows, "quality": quality,
        "validation": build_validation(store, protocol),
    }
    payload = validate_payload(data, vocab)
    return payload, {v: k for k, v in orgs.items()}


def cohen_kappa(a: pd.Series, b: pd.Series) -> float | None:
    """Binary Cohen's κ; None when fewer than 2 pairs or when expected agreement is 1 (undefined)."""
    a, b = a.astype(bool).to_numpy(), b.astype(bool).to_numpy()
    n = len(a)
    if n < 2:
        return None
    po = float((a == b).mean())
    pe = float(a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean()))
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def build_validation(store: Store, protocol: Protocol) -> dict | None:
    """Evaluation-only (spec §6): present only when `auditpace estimate --coverage` wrote `coverage`,
    the one S6 path that reads cases.breached. Nothing else in S8 touches structured truth."""
    if not store.exists("coverage"):
        return None
    cov = store.read("coverage")
    v = store.read("verdicts")[["case_id", "criterion_id", "status", "reason_tag"]]
    cases = store.read("cases")[["case_id", "breached", "true_reason"]]
    m = v.merge(cases, on="case_id", how="inner")
    kappa, acc = [], []
    for cid in [c.id for c in protocol.criteria]:
        sub = m[(m.criterion_id == cid) & (m.status != "abstain")]
        if sub.empty:
            continue
        kappa.append({"criterion_id": cid, "kappa": cohen_kappa(sub.status == "breached", sub.breached), "n": len(sub)})
        br = sub[sub.status == "breached"]
        acc.append({"criterion_id": cid, "n": len(br),
                    "acc": None if br.empty else float((br.reason_tag.astype(object) == br.true_reason.astype(object)).mean())})
    # Sort by criterion/fraction, then naive before corrected (matches the naive->corrected order
    # used everywhere else in the payload); sorting "method" lexicographically would put "corrected"
    # first, which reads backwards next to the rate it corrects.
    cov = cov.assign(_method_order=cov.method.map({"naive": 0, "corrected": 1}))
    cov_sorted = cov.sort_values(["criterion_id", "fraction", "_method_order"])
    return {"present": True,
            "coverage": [{"criterion_id": r.criterion_id, "fraction": float(r.fraction), "method": r.method,
                          "coverage": float(r.coverage), "mean_width": float(r.mean_width)}
                         for r in cov_sorted.itertuples()],
            "kappa": kappa, "reason_accuracy": acc}


class GatewayLog:
    """Append-only JSONL, one line per event, written to every path (the shared log and the run's copy)."""

    def __init__(self, paths: list[Path]):
        self.paths = [Path(p) for p in paths]

    def write(self, status: str, run_id: str, **fields) -> None:
        line = json.dumps({"ts": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%S"), "run_id": run_id,
                           "status": status, **fields}, sort_keys=False, default=str)
        for p in self.paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    @staticmethod
    def lines(path: Path) -> list[dict]:
        path = Path(path)
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
