"""Deterministic document plan per patient (S2 design §5): which documents exist, when they were
authored, which planted facts each must carry. The model never chooses any of this."""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from auditpace.cohort.plant import stable_int
from auditpace.protocol import Criterion
from auditpace.synth.facts import Fact, distractor_fact, reason_fact, time_fact

DOC_TYPES = ["lab_report", "ed_clerking", "ward_round", "icu_note", "discharge_summary", "clinic_letter"]

# doc_type -> (anchor events (latest present wins), offset hours lo, hi). Every document is
# authored after the events whose times it carries (ward_round after enoxaparin, icu_note after
# ventilated); ed_clerking is additionally pulled before icu in build_plan.
_ANCHOR: dict[str, tuple[tuple[str, ...], float, float]] = {
    "lab_report": (("confirmed",), 0, 6),
    "ed_clerking": (("admitted",), 0.5, 3),
    "ward_round": (("admitted", "enoxaparin"), 1, 24),
    "icu_note": (("icu", "ventilated"), 1, 4),
    "discharge_summary": (("discharged",), 0, 48),
    "clinic_letter": (("follow_up",), 0, 168),
}
# criterion `to` event -> document carrying both of its timestamps
_TIME_CARRIER = {"confirmed": "lab_report", "admitted": "ed_clerking", "icu": "icu_note",
                 "enoxaparin": "ward_round", "ventilated": "icu_note", "follow_up": "clinic_letter"}
# criterion `to` event -> documents (first present wins) carrying its reason / distractor
_REASON_CARRIER = {"confirmed": ("ed_clerking", "lab_report"), "admitted": ("ed_clerking", "lab_report"),
                   "icu": ("icu_note",), "enoxaparin": ("ward_round",), "ventilated": ("icu_note",),
                   "follow_up": ("clinic_letter",)}
_HANDWRITTEN_TYPES = {"ed_clerking", "ward_round"}
_HANDWRITTEN_SHARE = 0.20
_DISTRACTOR_SHARE = 0.30
_END_OF_DAY = pd.Timedelta(hours=23, minutes=59)


@dataclass(frozen=True)
class DocSpec:
    doc_id: str
    patient_id: str
    doc_type: str
    authored_ts: pd.Timestamp
    style: str
    known_events: tuple[tuple[str, pd.Timestamp], ...]
    facts: tuple[Fact, ...]
    died: pd.Timestamp | None


def _timeline(events: pd.DataFrame) -> dict[str, pd.Timestamp]:
    has_planted = "planted_ts" in events.columns
    tl = {}
    for r in events.itertuples():
        t = r.planted_ts if has_planted and pd.notna(r.planted_ts) else r.ts
        tl[r.event_type] = pd.Timestamp(t)
    return tl


def build_plan(patient: pd.Series, events: pd.DataFrame, cases: pd.DataFrame, criteria: list[Criterion],
               event_order: list[str], seed: int) -> list[DocSpec]:
    pid = str(patient.patient_id)
    tl = _timeline(events)
    died = tl.get("died")
    died_cap = died.normalize() + _END_OF_DAY if died is not None else None

    authored: dict[str, pd.Timestamp] = {}
    for doc_type, (anchors, lo, hi) in _ANCHOR.items():
        present = [tl[a] for a in anchors if a in tl]
        if not present:
            continue
        # Use died_cap (end of the death day), not died itself: Synthea death dates are
        # date-only (always midnight), so a same-day follow_up would otherwise look like it
        # happened "after death" and get dropped here while the cases loop below (which does
        # use died_cap) still expects a clinic_letter carrier for it -> crash. Matches the
        # died_cap convention used everywhere else in this function for the same reason.
        if doc_type == "clinic_letter" and died is not None and died_cap < tl["follow_up"]:
            continue
        rng = np.random.default_rng(seed + stable_int(f"{pid}:{doc_type}"))
        ts = max(present) + pd.Timedelta(hours=float(rng.uniform(lo, hi)))
        if doc_type == "ed_clerking" and "icu" in tl and ts >= tl["icu"]:
            ts = tl["icu"] - pd.Timedelta(minutes=5)  # H3 floors icu at admitted + 15 min, so still after admitted
        if died_cap is not None and ts > died_cap:
            ts = died_cap
        # whole minutes (the prompt shows authored_ts to the minute); ceil rather than floor so an
        # offset under 60 s can never put the document before its anchor event
        authored[doc_type] = ts.ceil("min")

    facts: dict[str, list[Fact]] = {t: [] for t in authored}
    by_id = {c.id: c for c in criteria}
    for r in cases.itertuples():
        if not r.applies or pd.isna(r.start_ts) or pd.isna(r.end_ts):
            continue
        c = by_id[r.criterion_id]
        if died_cap is not None and pd.Timestamp(r.end_ts) > died_cap:
            continue  # event planted after death (S1 artefact): no document can record it
        if c.to not in _TIME_CARRIER:
            raise ValueError(f"no document carrier for event {c.to!r} (criterion {c.id})")
        carrier = _TIME_CARRIER[c.to]
        if carrier not in facts:
            raise ValueError(f"{r.case_id}: carrier {carrier!r} absent from plan")
        facts[carrier].append(time_fact(r.case_id, c.from_, r.start_ts))
        facts[carrier].append(time_fact(r.case_id, c.to, r.end_ts))
        reason_doc = next((d for d in _REASON_CARRIER[c.to] if d in facts), None)
        if reason_doc is None:
            raise ValueError(f"{r.case_id}: no reason carrier present")
        if r.breached:
            facts[reason_doc].append(reason_fact(r.case_id, c.id, str(r.true_reason), seed))
        elif np.random.default_rng(seed + stable_int(f"{r.case_id}:distractor_draw")).random() < _DISTRACTOR_SHARE:
            facts[reason_doc].append(distractor_fact(r.case_id, c.id, seed))

    specs = []
    for doc_type in DOC_TYPES:
        if doc_type not in authored:
            continue
        ts = authored[doc_type]
        doc_id = f"{pid}:{doc_type}"
        style = "typed"
        if doc_type in _HANDWRITTEN_TYPES and np.random.default_rng(seed + stable_int(doc_id)).random() < _HANDWRITTEN_SHARE:
            style = "handwritten"
        known = tuple(sorted(((e, t) for e, t in tl.items() if e != "died" and t <= ts),
                             key=lambda et: event_order.index(et[0]) if et[0] in event_order else len(event_order)))
        specs.append(DocSpec(doc_id, pid, doc_type, ts, style, known, tuple(facts[doc_type]), died))
    return specs
