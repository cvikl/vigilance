import json
import re

import pandas as pd
import pytest

from auditpace.report.gateway import (
    GatewayLog,
    GatewayViolation,
    Payload,
    build_payload,
    cohen_kappa,
    validate_payload,
)
from auditpace.store import Store
from tests.report.conftest import NOW, minimal_payload

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}")


def test_vocab_from_protocol(vocab, toy_protocol):
    assert vocab.criterion_ids == frozenset(c.id for c in toy_protocol.criteria)
    assert "undetermined" in vocab.reasons["H4"] and "not_prescribed" in vocab.reasons["H4"]
    assert toy_protocol.owner("H4") in vocab.owners
    assert toy_protocol.action("H4", "not_prescribed") in vocab.actions
    assert vocab.segment_values["sex"] == frozenset({"F"})
    assert "organization" in vocab.segment_keys and "organization" not in vocab.segment_values


def test_minimal_payload_validates(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    assert isinstance(p, Payload)
    assert p.criteria[0].segments[1].corrected.rate is None


def test_extra_field_rejected(vocab, toy_protocol):
    d = minimal_payload(toy_protocol)
    d["criteria"][0]["quote"] = "Admitted 14:20"
    with pytest.raises(GatewayViolation) as e:
        validate_payload(d, vocab)
    assert "quote" in str(e.value)


POISON = ["Admitted to hospital at 14:20 on 12/03/2020", "1f6e17d1-4c15-4397-9c4f-753e89c1d114:H4",
          "1f6e17d14c1543979c4f753e89c1d114", "please re-check the chart", "SpO2 82"]


def _string_paths(obj, prefix=""):
    """Every (dotted path, value) pair for a str leaf in a nested dict/list."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _string_paths(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _string_paths(v, f"{prefix}[{i}]")
    elif isinstance(obj, str):
        yield prefix, obj


def _set_path(obj, path, value):
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    cur = obj
    for part in parts[:-1]:
        cur = cur[int(part[1:-1])] if part.startswith("[") else cur[part]
    last = parts[-1]
    if last.startswith("["):
        cur[int(last[1:-1])] = value
    else:
        cur[last] = value


@pytest.mark.parametrize("poison", POISON)
def test_fuzz_every_string_field_rejects_poison(vocab, toy_protocol, poison):
    base = minimal_payload(toy_protocol)
    paths = [p for p, _ in _string_paths(base)]
    assert len(paths) > 30
    for path in paths:
        d = minimal_payload(toy_protocol)
        _set_path(d, path, poison)
        leaf = path.split(".")[-1].split("[")[0]
        with pytest.raises(GatewayViolation) as e:
            validate_payload(d, vocab)
        assert leaf in str(e.value) or path in str(e.value), (
            f"path {path!r} (poison {poison!r}) raised {e.value!r} which names neither the leaf nor the path"
        )


def test_for_model_strips_volatile_run_fields(vocab, toy_protocol):
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    m = p.for_model()
    for k in ("run_id", "generated_ts", "code_sha", "estimates_computed_ts"):
        assert k not in m["run"]
    assert m["run"]["protocol_hash"] == toy_protocol.hash
    # protocol_hash is a legitimate 64-hex value and is itself a 32+-hex run, so it trips UUID_RE
    # (a real case_id/patient_id detector) as a false positive; redact the one hash this payload
    # is allowed to carry before scanning the rest for a leaked id.
    assert not UUID_RE.search(json.dumps(m).replace(toy_protocol.hash, ""))


def _no_key(obj, name) -> bool:
    """True iff no dict in the nested structure has a key called `name`."""
    if isinstance(obj, dict):
        return name not in obj and all(_no_key(v, name) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_key(v, name) for v in obj)
    return True


def test_for_model_is_compact(vocab, toy_protocol):
    """Payload.for_model() (fix wave 1, controller ruling) is the compact, pre-formatted view the
    reporter actually sees — not model_dump(). It must carry no volatile run field, no `validation`,
    no raw `lo`/`hi` (every rate is a formatted string), no organisation segment row, and every
    figure must be the exact fmt.pct/ci/hours/num string (so a model that copies it verbatim always
    passes check_prose, which computes its printed-token set from the full Payload independently)."""
    p = validate_payload(minimal_payload(toy_protocol), vocab)
    m = p.for_model()
    for k in ("run_id", "generated_ts", "code_sha", "estimates_computed_ts", "reporter"):
        assert k not in m["run"]
    assert m["run"]["protocol_hash"] == toy_protocol.hash
    for bad in ("lo", "hi", "validation"):
        assert _no_key(m, bad), f"for_model() output carries a {bad!r} key"
    for c in m["criteria"]:
        assert all(s["key"] != "organization" for s in c["segments"])
    h4 = next(c for c in m["criteria"] if c["id"] == "H4")
    assert h4["corrected"] == "28.6 % (10.0–50.0 %)"
    assert not UUID_RE.search(json.dumps(m).replace(toy_protocol.hash, ""))
    # `for_model()` is meaningfully smaller than the full payload even on this single-criterion,
    # single-alert fixture (no volatile run fields, no validation, the one organisation segment
    # dropped); it does NOT reach half here — `standard`/`name`/`action`/`owner` narrative text and
    # the 64-hex protocol_hash are fixed per-run costs that dominate a payload this small, and they
    # are identical in both representations. The dramatic cut this fix wave is actually about — the
    # real cohort's 79,298-token payload, mostly dozens of per-organisation segment rows per
    # criterion that `for_model()` drops entirely — is measured in test_for_model_scale.py, where
    # the same view stays under 25,000 characters however many organisations the cohort has.
    assert len(json.dumps(m)) < 0.9 * len(p.model_dump_json())


RUN_ID = "rpt-20260917T120000-0badf00d"


def _build(toy_store, toy_protocol, mini_settings, **kw):
    with Store(toy_store, read_only=True) as store:
        return build_payload(store, toy_protocol, mini_settings, run_id=RUN_ID, now=NOW, code_sha="abc1234",
                             reporter_model=None, reporter_version=None, **kw)


def test_build_payload_from_toy_store(toy_store, toy_protocol, mini_settings):
    payload, _org_map = _build(toy_store, toy_protocol, mini_settings)
    ids = [c.id for c in payload.criteria]
    assert ids == ["H2", "H4", "H6"]  # only criteria present in the toy verdicts, protocol order
    h4 = next(c for c in payload.criteria if c.id == "H4")
    assert h4.n == 14 and h4.n_breached_system == 3 and h4.n_breached_legitimate == 1
    assert h4.owner == toy_protocol.owner("H4")
    assert {r.code for r in h4.reasons} == set(toy_protocol.criteria[3].reasons) | {"undetermined"}
    assert h4.provisional_reason == "fewer than 2 reviews"
    assert h4.method == "naive" and h4.flag == "n_reviewed_insufficient"
    # toy ROWS (tests/workbench/conftest.py) has 21 total cases across H2/H4/H6 (14 + 1 abstain +
    # 1 no-end + 5 not-breached); n_cases = sum(n) + sum(n_abstain) + sum(n_no_end) = 19 + 1 + 1.
    assert payload.quality.n_cases == 21 and payload.quality.n_unverified_cites == 1
    assert payload.run.run_id == RUN_ID and payload.run.code_sha == "abc1234"
    assert payload.run.adjudicator.prompt_version == "adj-test"
    assert payload.run.adjudicator.model == "m"
    assert payload.validation is None


def test_build_payload_pseudonymises_organisations(toy_store, toy_protocol, mini_settings):
    payload, org_map = _build(toy_store, toy_protocol, mini_settings)
    assert set(org_map) == {"Org-01", "Org-02"} and set(org_map.values()) == {"orgA", "orgB"}
    blob = json.dumps(payload.model_dump(mode="json"))
    assert "orgA" not in blob and "orgB" not in blob
    # protocol_hash is a legitimate 64-hex value that itself trips UUID_RE's 32-hex-run branch as a
    # false positive (see test_for_model_strips_volatile_run_fields); redact it before scanning.
    assert not UUID_RE.search(blob.replace(toy_protocol.hash, ""))
    # stable: ranking by n desc then id
    _payload2, org_map2 = _build(toy_store, toy_protocol, mini_settings)
    assert org_map2 == org_map


def test_build_payload_never_carries_justification_or_quotes(toy_store, toy_protocol, mini_settings):
    payload, _ = _build(toy_store, toy_protocol, mini_settings)
    blob = json.dumps(payload.model_dump(mode="json"))
    assert "justification" not in blob and "quote" not in blob and "rationale" not in blob
    assert "priority_reason" not in blob and "note" not in blob.replace("caveats_note", "")


def test_build_payload_counts_reviews_via_latest(toy_store, toy_protocol, mini_settings):
    from auditpace.estimate.reviews import assign_pool, review_frame
    h = toy_protocol.hash
    rows = []
    for i, (state, status) in enumerate([("validated", "breached"), ("disputed", "not_breached"), ("flagged", None)]):
        rows.append({"review_id": f"r{i}", "case_id": "sys:H4", "reviewer": "clinician", "validation_state": state,
                     "human_status": status, "human_reason": "not_prescribed" if status == "breached" else None,
                     "note": "SECRET NOTE", "pool": assign_pool("sys:H4", h, 0.8),
                     "reviewed_ts": pd.Timestamp("2026-09-17 10:00:00") + pd.Timedelta(seconds=i), "protocol_hash": h})
    with Store(toy_store) as store:
        for i, r in enumerate(rows):
            store.write_part("reviews", f"r{i}", review_frame([r]), h)
    payload, _ = _build(toy_store, toy_protocol, mini_settings)
    q = payload.quality.reviews
    assert q.n_latest == 1 and q.n_flagged == 1 and q.n_validated == 0 and q.n_disputed == 0
    assert q.reviewers == ["clinician"]
    assert "SECRET NOTE" not in json.dumps(payload.model_dump(mode="json"))


def test_build_payload_rejects_poisoned_action(toy_store, toy_protocol, mini_settings):
    with Store(toy_store) as store:
        al = store.read("alerts")
        al.loc[0, "action"] = "Call patient 1f6e17d1-4c15-4397-9c4f-753e89c1d114 now"
        store.write("alerts", al, toy_protocol.hash)
    with pytest.raises(GatewayViolation, match="alerts\\[0\\].action"):
        _build(toy_store, toy_protocol, mini_settings)


def test_gateway_log_appends_jsonl_to_every_path(tmp_path):
    a, b = tmp_path / "a" / "gateway.log", tmp_path / "b" / "gateway.log"
    log = GatewayLog([a, b])
    log.write("sent", "rpt-20260917T120000-0badf00d", model="m", sha256="00" * 32, n_bytes=10)
    log.write("rejected", "rpt-20260917T120000-0badf00d", field="alerts[0].action", reason="x")
    for p in (a, b):
        lines = GatewayLog.lines(p)
        assert [x["status"] for x in lines] == ["sent", "rejected"]
        assert lines[0]["run_id"] == "rpt-20260917T120000-0badf00d" and "ts" in lines[0]
    log.write("sent", "rpt-20260917T120001-0badf00d")
    assert len(GatewayLog.lines(a)) == 3  # append, never truncate


def test_cohen_kappa():
    a = pd.Series([True, True, False, False, True, False])
    assert cohen_kappa(a, a) == pytest.approx(1.0)
    assert cohen_kappa(a, ~a) == pytest.approx(-1.0)
    assert cohen_kappa(pd.Series([True, True]), pd.Series([True, True])) is None  # no variance → undefined
    assert cohen_kappa(pd.Series([], dtype=bool), pd.Series([], dtype=bool)) is None


def test_validation_absent_without_coverage(toy_store, toy_protocol, mini_settings):
    payload, _ = _build(toy_store, toy_protocol, mini_settings)
    assert payload.validation is None


def test_validation_present_with_coverage(toy_store, toy_protocol, mini_settings):
    cov = pd.DataFrame([{"criterion_id": "H4", "fraction": 0.1, "method": "naive", "coverage": 0.6, "mean_width": 0.2,
                         "n_sims": 10, "n": 14, "computed_ts": NOW},
                        {"criterion_id": "H4", "fraction": 0.1, "method": "corrected", "coverage": 0.95, "mean_width": 0.3,
                         "n_sims": 10, "n": 14, "computed_ts": NOW}])
    with Store(toy_store) as store:
        store.write("coverage", cov, toy_protocol.hash)
    payload, _ = _build(toy_store, toy_protocol, mini_settings)
    v = payload.validation
    assert v is not None and [r.method for r in v.coverage] == ["naive", "corrected"]
    k = {r.criterion_id: r for r in v.kappa}
    # H2's only row is an abstain; build_validation skips criteria with zero non-abstain verdicts,
    # so H2 has no kappa row (controller ruling — the toy fixture's H2 row is `status="abstain"`).
    assert set(k) == {"H4", "H6"}
    assert k["H4"].n == 14 and k["H4"].kappa == pytest.approx(1.0)  # toy truth == status
    acc = {r.criterion_id: r for r in v.reason_accuracy}
    assert acc["H4"].n == 4 and acc["H4"].acc == pytest.approx(1.0)
    assert "H2" not in acc
