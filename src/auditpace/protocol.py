"""Protocol: the locked, clinician-approved definition of one audit (see CONTEXT.md)."""
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ProtocolNotLocked(RuntimeError):
    pass


class SampleRule(BaseModel):
    n: int
    seed: int = 42
    stratify_by: list[str] = Field(default_factory=list)


class CohortRule(BaseModel):
    include: dict[str, list[int] | list[str]]
    require_any: dict[str, list[str]] = Field(default_factory=dict)
    period: dict[str, date] | None = None
    sample: SampleRule


class EventRule(BaseModel):
    """Deterministic derivation of one PathwayEvent from a structured table."""
    table: Literal["conditions", "encounters", "procedures", "medications", "observations", "patients"]
    code: int | list[int] | None = None
    description_contains: str | None = None
    rxnorm_contains: str | None = None
    reason_code: int | None = None
    field: str | None = None
    after: str | None = None
    # encounters only
    class_: str | list[str] | None = Field(default=None, alias="class")

    model_config = {"populate_by_name": True}


class Criterion(BaseModel):
    id: str
    name: str
    type: Literal["handoff"]
    from_: str = Field(alias="from")
    to: str
    target_hours: float
    standard: str
    reasons: list[str]
    applies_when: dict[str, str] | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _reasons_have_other(self) -> "Criterion":
        if "other" not in self.reasons:
            raise ValueError(f"criterion {self.id}: reasons must include 'other'")
        return self


class ReviewConfig(BaseModel):
    fraction: float = 1.0
    estimation_pool_fraction: float = 0.8
    confidence: float = 0.95


class SyntheticConfig(BaseModel):
    """Only honoured on synthetic data: plant times-of-day and breach status (spec §6 stage 1)."""
    augment_times: bool = False
    breach_rates: dict[str, float] = Field(default_factory=dict)


class ReasonAction(BaseModel):
    class_: Literal["system", "legitimate"] = Field(alias="class")
    action: str

    model_config = {"populate_by_name": True}


class CriterionActions(BaseModel):
    """Operational metadata for one criterion: who owns the fix, what to do per reason, and
    whether a reason means the patient is legitimately waiting. Hash-exempt (ADR 0005)."""
    owner: str
    compliance_target: float | None = Field(default=None, ge=0.0, le=1.0)
    reasons: dict[str, ReasonAction]


ActionsConfig = dict[str, CriterionActions]


class Protocol(BaseModel):
    protocol_id: str
    question: str
    cohort: CohortRule
    events: dict[str, EventRule]
    criteria: list[Criterion]
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    synthetic: SyntheticConfig | None = None
    segments: list[str] = Field(default_factory=list)
    suppress_below: int = 5
    actions: ActionsConfig | None = None
    locked: bool = False
    hash: str | None = None

    @model_validator(mode="after")
    def _criteria_reference_known_events(self) -> "Protocol":
        ids = {c.id for c in self.criteria}
        for c in self.criteria:
            for ev in (c.from_, c.to):
                if ev not in self.events:
                    raise ValueError(f"criterion {c.id} references unknown event '{ev}'")
            if c.applies_when and "has_event" in c.applies_when and c.applies_when["has_event"] not in self.events:
                raise ValueError(f"criterion {c.id} applies_when references unknown event")
        if self.synthetic:
            unknown = set(self.synthetic.breach_rates) - ids
            if unknown:
                raise ValueError(f"synthetic.breach_rates has unknown criteria {sorted(unknown)}")
        if self.actions:
            by_id = {c.id: c for c in self.criteria}
            for cid, acts in self.actions.items():
                if cid not in by_id:
                    raise ValueError(f"actions: unknown criterion '{cid}'")
                taxonomy = set(by_id[cid].reasons)
                extra = set(acts.reasons) - taxonomy
                if extra:
                    raise ValueError(f"actions.{cid}: reasons {sorted(extra)} not in criterion taxonomy")
                missing = taxonomy - set(acts.reasons)
                if missing:
                    raise ValueError(f"actions.{cid}: unmapped reasons {sorted(missing)}")
        return self

    def _acts(self, criterion_id: str) -> CriterionActions | None:
        return (self.actions or {}).get(criterion_id)

    def reason_class(self, criterion_id: str, reason: str | None) -> str:
        """'system' | 'legitimate' for a taxonomy code; 'system' when no block. Callers map a null
        reason to 'undetermined' themselves — this never sees None."""
        a = self._acts(criterion_id)
        if a is None or reason not in a.reasons:
            return "system"
        return a.reasons[reason].class_

    def owner(self, criterion_id: str) -> str:
        a = self._acts(criterion_id)
        return a.owner if a else "unassigned"

    def action(self, criterion_id: str, reason: str | None) -> str:
        a = self._acts(criterion_id)
        if a is None:
            return "unassigned"
        if reason in a.reasons:
            return a.reasons[reason].action
        return a.reasons["other"].action

    def compliance_target(self, criterion_id: str) -> float | None:
        a = self._acts(criterion_id)
        return a.compliance_target if a else None


def load_protocol(path: Path | str = "protocol.yaml") -> Protocol:
    return Protocol.model_validate(yaml.safe_load(Path(path).read_text()))


def canonical_hash(p: Protocol) -> str:
    data = p.model_dump(by_alias=True, mode="json", exclude_defaults=True)
    data.pop("locked", None)
    data.pop("hash", None)
    data.pop("actions", None)  # operational metadata, hash-exempt (ADR 0005)
    blob = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


_LOCKED_LINE_RE = re.compile(r"^locked:\s*.*$", re.MULTILINE)
_HASH_LINE_RE = re.compile(r"^hash:\s*.*$", re.MULTILINE)


def lock_protocol(path: Path | str = "protocol.yaml") -> str:
    """Lock the protocol in place, writing `locked: true` and the hash.

    Preserves the file's text (including comments) by patching the top-level
    `locked:`/`hash:` lines in place with a regex; falls back to a full
    `yaml.safe_dump` round-trip (which loses comments) only if the file
    doesn't already have both lines to patch.
    """
    path = Path(path)
    p = load_protocol(path)
    h = canonical_hash(p)
    text = path.read_text()
    if _LOCKED_LINE_RE.search(text) and _HASH_LINE_RE.search(text):
        text = _LOCKED_LINE_RE.sub("locked: true", text, count=1)
        text = _HASH_LINE_RE.sub(f"hash: {h}", text, count=1)
        path.write_text(text)
    else:
        data = yaml.safe_load(text)
        data["locked"] = True
        data["hash"] = h
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return h


def require_locked(p: Protocol) -> None:
    if not p.locked or not p.hash:
        raise ProtocolNotLocked("protocol is not locked; run `auditpace protocol lock`")
    if canonical_hash(p) != p.hash:
        raise ProtocolNotLocked("protocol was edited after locking; re-lock")
