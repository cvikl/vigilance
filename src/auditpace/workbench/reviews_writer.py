"""The `reviews` write path: one parquet partition per submission (spec §3)."""
import uuid
from pathlib import Path

import pandas as pd

from auditpace.estimate.reviews import assign_pool, review_frame
from auditpace.protocol import Protocol
from auditpace.store import Store

ACTIONS = {"confirm": "validated", "override": "disputed", "flag": "flagged"}


def form_to_review(action: str, verdict_status: str, verdict_reason: str | None,
                   human_status: str | None, human_reason: str | None) -> tuple[str, str | None, str | None]:
    """Confirm copies the verdict; Override takes the reviewer's call; Flag records no call (rubric C1)."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {sorted(ACTIONS)}, got {action!r}")
    state = ACTIONS[action]
    if action == "confirm":
        return state, verdict_status, (verdict_reason if verdict_status == "breached" else None)
    if action == "override":
        return state, human_status, (human_reason if human_status == "breached" else None)
    return state, None, None


def write_review(processed_dir: Path, protocol: Protocol, *, case_id: str, reviewer: str, validation_state: str,
                 human_status: str | None, human_reason: str | None, note: str | None,
                 now: pd.Timestamp | None = None) -> str:
    """Validate through `review_frame` (raises ValueError), pool deterministically, write atomically.
    The writable store lives only inside this call so it never overlaps a read-only snapshot load."""
    review_id = uuid.uuid4().hex
    now = now if now is not None else pd.Timestamp.now("UTC").tz_localize(None)
    row = {
        "review_id": review_id, "case_id": case_id, "reviewer": reviewer or "clinician",
        "validation_state": validation_state, "human_status": human_status or None,
        "human_reason": human_reason or None, "note": note or None,
        "pool": assign_pool(case_id, protocol.hash, protocol.review.estimation_pool_fraction),
        "reviewed_ts": now, "protocol_hash": protocol.hash,
    }
    df = review_frame([row])
    with Store(processed_dir) as store:
        store.write_part("reviews", f"r_{review_id}", df, protocol.hash)
    return review_id
