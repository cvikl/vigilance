"""Planted facts: verbatim strings the model must embed (S2 design §6).

Reason and distractor phrasings live in yaml banks beside this module, keyed by criterion id and
reason code, so wording can change without touching the locked protocol.
"""
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from auditpace.cohort.plant import stable_int
from auditpace.protocol import Criterion

_DIR = Path(__file__).parent
REASONS: dict[str, dict[str, list[str]]] = yaml.safe_load((_DIR / "reasons.yaml").read_text())
DISTRACTORS: dict[str, list[str]] = yaml.safe_load((_DIR / "distractors.yaml").read_text())
_MIN_VARIANTS = 3
TIME_FORMAT = "%H:%M on %d/%m/%Y"


@dataclass(frozen=True)
class Fact:
    fact_id: str
    case_id: str
    kind: str  # "time" | "reason" | "distractor"
    text: str
    event_type: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def check_bank(criteria: list[Criterion]) -> None:
    """Fail loud if any protocol (criterion, reason) lacks >= 3 phrasings or a distractor set."""
    missing = []
    for c in criteria:
        for r in c.reasons:
            if len(REASONS.get(c.id, {}).get(r, [])) < _MIN_VARIANTS:
                missing.append(f"{c.id}.{r}")
        if len(DISTRACTORS.get(c.id, [])) < _MIN_VARIANTS:
            missing.append(f"{c.id}.<distractor>")
    if missing:
        raise ValueError(f"phrase bank incomplete (need >= {_MIN_VARIANTS} variants): {missing}")


def time_text(ts) -> str:
    return pd.Timestamp(ts).strftime(TIME_FORMAT)


def time_fact(case_id: str, event_type: str, ts) -> Fact:
    return Fact(f"{case_id}:time:{event_type}", case_id, "time", time_text(ts), event_type)


def _pick(variants: list[str], key: str, seed: int) -> str:
    rng = np.random.default_rng(seed + stable_int(key))
    return variants[int(rng.integers(len(variants)))]


def reason_fact(case_id: str, criterion_id: str, reason: str, seed: int) -> Fact:
    return Fact(f"{case_id}:reason", case_id, "reason", _pick(REASONS[criterion_id][reason], f"{case_id}:reason", seed))


def distractor_fact(case_id: str, criterion_id: str, seed: int) -> Fact:
    return Fact(f"{case_id}:distractor", case_id, "distractor", _pick(DISTRACTORS[criterion_id], f"{case_id}:distractor", seed))
