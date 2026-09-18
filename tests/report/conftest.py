"""S8 fixtures: the S7 toy processed dir plus S6 tables written by compute_all."""
from pathlib import Path

import pandas as pd
import pytest

from auditpace.estimate.compute import compute_all
from auditpace.report.gateway import Vocab
from auditpace.store import Store
from tests.workbench.conftest import (  # noqa: F401  (re-exported fixtures)
    toy_processed,
    toy_protocol,
)

NOW = pd.Timestamp("2026-09-17 12:00:00")


@pytest.fixture
def toy_store(toy_processed: Path, toy_protocol) -> Path:  # noqa: F811
    """processed/ with estimates, funnel, runchart, timelost, alerts, queue and cohort_completeness."""
    with Store(toy_processed) as store:
        out = compute_all(store, toy_protocol, NOW)
        for name, df in out.items():
            store.write(name, df, toy_protocol.hash)
        comp = pd.DataFrame([{"event_type": ev, "n_patients_with": 20, "n_patients_without": 0}
                             for ev in toy_protocol.events])
        store.write("cohort_completeness", comp, toy_protocol.hash)
    return toy_processed


@pytest.fixture
def vocab(toy_store, toy_protocol) -> Vocab:  # noqa: F811
    with Store(toy_store, read_only=True) as store:
        return Vocab.from_protocol(toy_protocol, store.read("patients"))


def minimal_payload(protocol) -> dict:
    """The smallest valid payload dict for the locked protocol: one criterion, one alert, no validation."""
    c = protocol.criteria[3]  # H4
    reasons = [{"code": r, "klass": protocol.reason_class(c.id, r), "action": protocol.action(c.id, r),
                "n": 1, "rate": 0.1, "lo": 0.05, "hi": 0.2} for r in c.reasons]
    reasons.append({"code": "undetermined", "klass": "undetermined", "action": protocol.action(c.id, "other"),
                    "n": 0, "rate": 0.0, "lo": 0.0, "hi": 0.01})
    return {
        "payload_version": 1,
        "run": {"run_id": "rpt-20260917T120000-deadbeef", "protocol_id": protocol.protocol_id,
                "protocol_hash": protocol.hash, "code_sha": "abc1234", "period": {"start": "2020-01-01", "end": "2020-12-31"},
                "cohort_n": 20, "generated_ts": "2026-09-17T12:00:00",
                "adjudicator": {"model": "m", "prompt_version": "adj-000000000000"},
                "reader": {"read_version": "read-000000000000"},
                "reporter": {"model": None, "prompt_version": None},
                "review": {"estimation_pool_fraction": 0.8, "confidence": 0.95}, "suppress_below": 5,
                "estimates_computed_ts": "2026-09-17T12:00:00"},
        "completeness": [{"event": "admitted", "n_with": 20, "n_without": 0}],
        "criteria": [{
            "id": c.id, "name": c.name, "from_event": c.from_, "to_event": c.to, "target_hours": c.target_hours,
            "standard": c.standard, "owner": protocol.owner(c.id), "compliance_target": protocol.compliance_target(c.id),
            "n": 14, "n_reviewed": 0, "n_abstain": 0, "n_no_end": 0, "n_breached_system": 3,
            "n_breached_legitimate": 1, "n_breached_undetermined": 0,
            "naive": {"rate": 0.2857, "lo": 0.1, "hi": 0.5}, "corrected": {"rate": 0.2857, "lo": 0.1, "hi": 0.5},
            "method": "naive", "flag": "n_reviewed_insufficient", "provisional_reason": "fewer than 2 reviews",
            "rate_system": {"rate": 0.21, "lo": 0.1, "hi": 0.4}, "rate_legitimate": {"rate": 0.07, "lo": 0.0, "hi": 0.3},
            "rate_undetermined": {"rate": 0.0, "lo": 0.0, "hi": 0.2},
            "reasons": reasons,
            "segments": [{"key": "sex", "value": "F", "n": 14, "corrected": {"rate": 0.28, "lo": 0.1, "hi": 0.5},
                          "method": "naive", "suppressed": False},
                         {"key": "organization", "value": "Org-01", "n": 8, "corrected": {"rate": None, "lo": None, "hi": None},
                          "method": "naive", "suppressed": True},
                         {"key": "age_band", "value": "40-59", "n": 14, "corrected": {"rate": 0.2857, "lo": 0.1, "hi": 0.5},
                          "method": "naive", "suppressed": False}],
            "funnel": [{"org": "Org-02", "n": 6, "rate": 0.5, "lo": 0.2, "hi": 0.8, "signal": "alert_high"}],
            "runchart": {"n_weeks": 3, "latest": {"week": "2020-W12", "rate": 0.3, "lo": 0.1, "hi": 0.6},
                         "signals": [{"week": "2020-W11", "signal": "alert_high"}]},
            "timelost": {"hours_lost": 60.5, "median_excess_h": 8.0, "rank": 1},
        }],
        "alerts": [{"alert_id": "org_outlier:H4:Org-02", "kind": "org_outlier", "criterion_id": "H4",
                    "segment_key": "organization", "segment_value": "Org-02", "signal": "alert_high", "rate": 0.5,
                    "lo": 0.2, "hi": 0.8, "n": 6, "n_reviewed": 0, "method": "naive", "hours_lost": 30.0,
                    "dominant_reason": "not_prescribed", "action": protocol.action("H4", "not_prescribed"),
                    "owner": protocol.owner("H4")}],
        "quality": {"n_cases": 20, "n_abstain": 1, "n_no_end": 1, "abstain_rate": 0.05, "no_end_rate": 0.05,
                    "n_cites": 20, "n_unverified_cites": 1, "unverified_cite_rate": 0.05,
                    "quarantined": {"adjudicate": 0}, "n_suppressed_cells": 1,
                    "reviews": {"n_latest": 0, "n_validated": 0, "n_disputed": 0, "n_flagged": 0,
                                "n_estimation_pool": 0, "reviewers": []}},
        "validation": None,
    }
