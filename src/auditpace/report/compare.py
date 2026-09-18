"""Change since the previous run (spec §7): a pure diff of two payloads, no statistics, no prose."""
import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from auditpace.report.gateway import Payload

PAYLOAD_VERSION = 1


class CriterionDelta(BaseModel):
    criterion_id: str
    rate_prev: float | None
    lo_prev: float | None
    hi_prev: float | None
    rate_cur: float | None
    lo_cur: float | None
    hi_cur: float | None
    delta_pp: float | None
    n_reviewed_prev: int
    n_reviewed_cur: int
    method_prev: str
    method_cur: str
    provisional_prev: bool
    provisional_cur: bool


class Comparison(BaseModel):
    prev_run_id: str
    prev_generated_ts: str
    criteria: list[CriterionDelta]
    alerts_new: list[str]
    alerts_resolved: list[str]
    alerts_persisting: list[str]
    reviews_added: int
    org_map_changed: bool = False


def write_payload(report_dir: Path, payload: Payload, blob: str | None = None) -> Path:
    """Write payload.json. `blob` lets a caller (the stage) persist the exact bytes it already hashed
    for the gateway log's `sent` line; other callers get the default indented dump."""
    d = Path(report_dir) / payload.run.run_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "payload.json"
    p.write_text(blob if blob is not None else payload.model_dump_json(indent=1), encoding="utf-8")
    return p


def _load(p: Path) -> tuple[dict | None, str]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"unreadable payload {p.parent.name}: {e}"
    if not isinstance(data, dict):
        return None, f"unreadable payload {p.parent.name}: not a JSON object"
    return data, ""


def find_previous(report_dir: Path, protocol_hash: str, *, run_id: str | None = None,
                  exclude: str | None = None) -> tuple[Payload | None, str]:
    """Newest prior payload.json under report_dir with the same protocol hash and payload version, or
    the one named by run_id. Returns (payload, note); note is non-empty when nothing usable was found."""
    report_dir = Path(report_dir)
    if run_id is not None:
        candidates = [report_dir / run_id / "payload.json"]
    else:
        candidates = sorted((p for p in report_dir.glob("rpt-*/payload.json") if p.parent.name != exclude),
                            key=lambda p: p.parent.name, reverse=True)
    if not candidates or not candidates[0].exists():
        return None, "first run of this protocol" if run_id is None else f"no run {run_id}"
    data, note = _load(candidates[0])
    if data is None:
        return None, note
    if data.get("payload_version") != PAYLOAD_VERSION:
        return None, f"previous run {candidates[0].parent.name} has payload version {data.get('payload_version')}; no comparison"
    if data.get("run", {}).get("protocol_hash") != protocol_hash:
        return None, (f"previous run {candidates[0].parent.name} used a different protocol "
                      f"({str(data.get('run', {}).get('protocol_hash', ''))[:12]}); no comparison")
    try:
        return Payload.model_validate(data), ""
    except ValidationError as e:
        return None, (f"previous run {candidates[0].parent.name} has an invalid payload "
                      f"({e.error_count()} errors); no comparison")


def diff(prev: Payload, cur: Payload, org_map_changed: bool = False) -> Comparison:
    prev_by = {c.id: c for c in prev.criteria}
    rows = []
    for c in cur.criteria:
        p = prev_by.get(c.id)
        if p is None:
            continue
        delta = None if (p.corrected.rate is None or c.corrected.rate is None) else 100 * (c.corrected.rate - p.corrected.rate)
        rows.append(CriterionDelta(
            criterion_id=c.id, rate_prev=p.corrected.rate, lo_prev=p.corrected.lo, hi_prev=p.corrected.hi,
            rate_cur=c.corrected.rate, lo_cur=c.corrected.lo, hi_cur=c.corrected.hi, delta_pp=delta,
            n_reviewed_prev=p.n_reviewed, n_reviewed_cur=c.n_reviewed, method_prev=p.method, method_cur=c.method,
            provisional_prev=p.provisional_reason is not None, provisional_cur=c.provisional_reason is not None))
    prev_ids = {a.alert_id for a in prev.alerts}
    cur_ids = {a.alert_id for a in cur.alerts}
    return Comparison(prev_run_id=prev.run.run_id, prev_generated_ts=prev.run.generated_ts, criteria=rows,
                      alerts_new=sorted(cur_ids - prev_ids), alerts_resolved=sorted(prev_ids - cur_ids),
                      alerts_persisting=sorted(cur_ids & prev_ids),
                      reviews_added=cur.quality.reviews.n_latest - prev.quality.reviews.n_latest,
                      org_map_changed=org_map_changed)
