import json

import pytest

from auditpace.report.compare import Comparison, diff, find_previous, write_payload
from auditpace.report.gateway import Payload, validate_payload
from tests.report.conftest import minimal_payload


def _payload(toy_protocol, vocab, run_id, **changes) -> Payload:
    d = minimal_payload(toy_protocol)
    d["run"]["run_id"] = run_id
    for path, value in changes.items():
        cur = d
        parts = path.split(".")
        for part in parts[:-1]:
            cur = cur[int(part)] if part.isdigit() else cur[part]
        cur[parts[-1]] = value
    return validate_payload(d, vocab)


def test_find_previous_picks_newest_same_hash(tmp_path, toy_protocol, vocab):
    a = _payload(toy_protocol, vocab, "rpt-20260917T100000-aaaaaaaa")
    b = _payload(toy_protocol, vocab, "rpt-20260917T110000-bbbbbbbb")
    write_payload(tmp_path, a)
    write_payload(tmp_path, b)
    prev, note = find_previous(tmp_path, toy_protocol.hash, exclude="rpt-20260917T120000-cccccccc")
    assert prev.run.run_id == b.run.run_id and note == ""
    prev, note = find_previous(tmp_path, toy_protocol.hash, exclude=b.run.run_id)
    assert prev.run.run_id == a.run.run_id
    prev, note = find_previous(tmp_path, toy_protocol.hash, run_id=a.run.run_id)
    assert prev.run.run_id == a.run.run_id


def test_find_previous_skips_other_hash_or_version(tmp_path, toy_protocol, vocab):
    assert find_previous(tmp_path, toy_protocol.hash) == (None, "first run of this protocol")
    a = _payload(toy_protocol, vocab, "rpt-20260917T100000-aaaaaaaa")
    p = write_payload(tmp_path, a)
    d = json.loads(p.read_text())
    d["run"]["protocol_hash"] = "f" * 64
    p.write_text(json.dumps(d))
    prev, note = find_previous(tmp_path, toy_protocol.hash)
    assert prev is None and "different protocol" in note and "ffffffffffff" in note
    d["run"]["protocol_hash"] = toy_protocol.hash
    d["payload_version"] = 2
    p.write_text(json.dumps(d))
    prev, note = find_previous(tmp_path, toy_protocol.hash)
    assert prev is None and "payload version" in note


@pytest.mark.parametrize("body,expected_note", [
    ("[]", "not a JSON object"),
    ("null", "not a JSON object"),
    ("{", "unreadable"),
])
def test_find_previous_never_crashes_on_bad_prior_json(tmp_path, toy_protocol, body, expected_note):
    d = tmp_path / "rpt-20260917T100000-aaaaaaaa"
    d.mkdir(parents=True)
    (d / "payload.json").write_text(body)
    prev, note = find_previous(tmp_path, toy_protocol.hash)
    assert prev is None and expected_note in note


def test_find_previous_never_crashes_on_invalid_payload_shape(tmp_path, toy_protocol, vocab):
    a = _payload(toy_protocol, vocab, "rpt-20260917T100000-aaaaaaaa")
    p = write_payload(tmp_path, a)
    d = json.loads(p.read_text())
    d["criteria"] = "nonsense"
    p.write_text(json.dumps(d))
    prev, note = find_previous(tmp_path, toy_protocol.hash)
    assert prev is None and "invalid payload" in note


def test_diff_org_map_changed_flag(toy_protocol, vocab):
    """spec §7: `org_map_changed` is a plain argument to `diff`, computed by the caller (the stage)
    from the previous run's org_map.json — `diff` itself just carries it through onto Comparison."""
    prev = _payload(toy_protocol, vocab, "rpt-20260917T100000-aaaaaaaa")
    cur = _payload(toy_protocol, vocab, "rpt-20260917T110000-bbbbbbbb")
    assert diff(prev, cur).org_map_changed is False  # default
    assert diff(prev, cur, org_map_changed=True).org_map_changed is True


def test_diff_rates_alerts_reviews(toy_protocol, vocab):
    prev = _payload(toy_protocol, vocab, "rpt-20260917T100000-aaaaaaaa")
    cur = _payload(toy_protocol, vocab, "rpt-20260917T110000-bbbbbbbb", **{
        "criteria.0.corrected": {"rate": 0.2, "lo": 0.1, "hi": 0.3}, "criteria.0.n_reviewed": 25,
        "criteria.0.provisional_reason": None, "criteria.0.flag": None, "criteria.0.method": "ppi",
        "quality.reviews.n_latest": 25,
        "alerts": [{**minimal_payload(toy_protocol)["alerts"][0], "alert_id": "org_outlier:H4:Org-01",
                    "segment_value": "Org-01"}],
    })
    c = diff(prev, cur)
    assert isinstance(c, Comparison)
    d = c.criteria[0]
    assert d.criterion_id == "H4" and d.rate_prev == pytest.approx(0.2857) and d.rate_cur == 0.2
    assert d.delta_pp == pytest.approx(-8.57, abs=0.01)
    assert d.n_reviewed_prev == 0 and d.n_reviewed_cur == 25 and d.provisional_prev and not d.provisional_cur
    assert c.alerts_new == ["org_outlier:H4:Org-01"] and c.alerts_resolved == ["org_outlier:H4:Org-02"]
    assert c.alerts_persisting == [] and c.reviews_added == 25
    assert c.prev_run_id == prev.run.run_id and c.prev_generated_ts == prev.run.generated_ts
