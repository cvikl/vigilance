import re
from pathlib import Path

import pytest
import yaml

from auditpace.protocol import (
    Protocol,
    ProtocolNotLocked,
    canonical_hash,
    load_protocol,
    lock_protocol,
    require_locked,
)

ROOT = Path(__file__).resolve().parents[1]


def test_repo_protocol_validates():
    p = load_protocol(ROOT / "protocol.yaml")
    assert p.protocol_id == "covid_handoffs_v1"
    assert [c.id for c in p.criteria] == ["H1", "H2", "H3", "H4", "H5", "H6"]
    assert p.review.fraction == 1.0
    assert p.synthetic and p.synthetic.augment_times and p.synthetic.breach_rates["H4"] == 0.35
    assert p.events["admitted"].code == 1505002
    # protocol.yaml is locked for the real Synthea run (T7); the hash must still verify
    assert p.locked is True
    assert p.hash and canonical_hash(p) == p.hash


def test_criterion_events_must_exist():
    data = yaml.safe_load((ROOT / "protocol.yaml").read_text())
    data["criteria"][0]["from"] = "nonexistent"
    with pytest.raises(ValueError, match="nonexistent"):
        Protocol.model_validate(data)


def test_synthetic_breach_rates_must_name_known_criteria():
    data = yaml.safe_load((ROOT / "protocol.yaml").read_text())
    data["synthetic"]["breach_rates"]["H9"] = 0.1
    with pytest.raises(ValueError, match="H9"):
        Protocol.model_validate(data)


def test_reasons_must_include_other():
    data = yaml.safe_load((ROOT / "protocol.yaml").read_text())
    data["criteria"][0]["reasons"] = ["swab_delay"]
    with pytest.raises(ValueError, match="other"):
        Protocol.model_validate(data)


def test_lock_writes_hash_and_is_stable(tmp_path: Path):
    src = ROOT / "protocol.yaml"
    dst = tmp_path / "protocol.yaml"
    dst.write_text(src.read_text())
    h1 = lock_protocol(dst)
    p = load_protocol(dst)
    assert p.locked is True and p.hash == h1 and len(h1) == 64
    # hash ignores the locked/hash fields themselves
    assert canonical_hash(p) == h1


def test_require_locked_raises_on_unlocked():
    # protocol.yaml itself is locked (T7); build an unlocked copy in memory to test this path.
    data = yaml.safe_load((ROOT / "protocol.yaml").read_text())
    data["locked"] = False
    data["hash"] = None
    p = Protocol.model_validate(data)
    with pytest.raises(ProtocolNotLocked):
        require_locked(p)


def test_require_locked_rejects_edited_after_lock(tmp_path: Path):
    dst = tmp_path / "protocol.yaml"
    dst.write_text((ROOT / "protocol.yaml").read_text())
    lock_protocol(dst)
    data = yaml.safe_load(dst.read_text())
    data["question"] = data["question"] + " (edited)"
    dst.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    p = load_protocol(dst)
    with pytest.raises(ProtocolNotLocked):
        require_locked(p)


def test_lock_preserves_comments(tmp_path: Path):
    src = ROOT / "protocol.yaml"
    dst = tmp_path / "protocol.yaml"
    text = src.read_text()
    assert "# COVID-19" in text  # sanity: the fixture actually has a comment worth preserving
    # protocol.yaml itself is already locked (T7); rewrite the copy to the locked:false ->
    # true transition this test is meant to exercise, rather than testing a re-lock.
    text = re.sub(r"^locked:\s*.*$", "locked: false", text, count=1, flags=re.MULTILINE)
    text = re.sub(r"^hash:\s*.*$", "hash: null", text, count=1, flags=re.MULTILINE)
    dst.write_text(text)
    before = load_protocol(dst)
    assert before.locked is False and before.hash is None
    h = lock_protocol(dst)
    out = dst.read_text()
    assert "# COVID-19" in out
    p = load_protocol(dst)
    assert p.locked is True
    assert p.hash == h


def test_hash_ignores_added_defaulted_fields():
    class P2(Protocol):
        extra_thing: int = 0

    data = yaml.safe_load((ROOT / "protocol.yaml").read_text())
    p1 = Protocol.model_validate(data)
    p2 = P2.model_validate(data)
    assert canonical_hash(p1) == canonical_hash(p2)


REPO_HASH = "83174236e1209a2c64284626d213ffee57c1bec681193228446d1b630d2150d7"


def _proto_dict() -> dict:
    return yaml.safe_load((ROOT / "protocol.yaml").read_text())


def test_actions_block_is_hash_exempt():
    d = _proto_dict()
    assert "actions" in d, "protocol.yaml must carry the actions block"
    with_block = Protocol.model_validate(d)
    d2 = dict(d); d2.pop("actions")
    without = Protocol.model_validate(d2)
    assert canonical_hash(with_block) == canonical_hash(without) == REPO_HASH


def test_actions_accessors_with_and_without_block():
    d = _proto_dict()
    p = Protocol.model_validate(d)
    assert p.reason_class("H4", "contraindication_documented") == "legitimate"
    assert p.reason_class("H4", "not_prescribed") == "system"
    assert p.owner("H4") == "Ward pharmacist / trust VTE lead"
    assert p.action("H4", "drug_shortage") == "Pharmacy stock alert to procurement"
    assert p.compliance_target("H4") == 0.9 and p.compliance_target("H1") is None
    d.pop("actions")
    q = Protocol.model_validate(d)
    assert q.reason_class("H4", "contraindication_documented") == "system"
    assert q.owner("H4") == "unassigned" and q.action("H4", "other") == "unassigned"
    assert q.compliance_target("H4") is None


def test_actions_validation_rejects_bad_blocks():
    d = _proto_dict()
    bad = dict(d); bad["actions"] = {"H9": d["actions"]["H1"]}
    with pytest.raises(ValueError, match="unknown criterion"):
        Protocol.model_validate(bad)
    bad = dict(d); bad["actions"] = {"H1": {**d["actions"]["H1"], "reasons": {**d["actions"]["H1"]["reasons"], "nope": {"class": "system", "action": "x"}}}}
    with pytest.raises(ValueError, match="not in criterion"):
        Protocol.model_validate(bad)
    bad = dict(d); r = dict(d["actions"]["H1"]["reasons"]); r.pop("other")
    bad["actions"] = {"H1": {**d["actions"]["H1"], "reasons": r}}
    with pytest.raises(ValueError, match="unmapped"):
        Protocol.model_validate(bad)
    bad = dict(d); bad["actions"] = {"H1": {**d["actions"]["H1"], "reasons": {**d["actions"]["H1"]["reasons"], "other": {"class": "maybe", "action": "x"}}}}
    with pytest.raises(ValueError):
        Protocol.model_validate(bad)
