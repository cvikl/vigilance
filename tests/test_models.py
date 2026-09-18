import json
import subprocess
from pathlib import Path

import pytest

from auditpace.models import (
    ClaudeCLI,
    MockMissing,
    ModelClient,
    ModelJSONError,
    cache_key,
    client_for,
)
from auditpace.settings import ModelEndpoint

EP = ModelEndpoint(base_url="http://mock/v1", model="mock-27b")


def test_mock_replays_fixture(tmp_path: Path):
    msgs = [{"role": "user", "content": "hi"}]
    key = cache_key(EP.model, msgs, None, [])
    (tmp_path / "responses").mkdir()
    (tmp_path / "responses" / f"{key}.json").write_text(json.dumps({"content": '{"a": 1}'}))
    c = ModelClient(EP, mock=True, fixtures_dir=tmp_path)
    assert c.chat(msgs) == '{"a": 1}'
    assert c.chat_json(msgs) == {"a": 1}


def test_mock_missing_raises_with_key(tmp_path: Path):
    c = ModelClient(EP, mock=True, fixtures_dir=tmp_path)
    with pytest.raises(MockMissing):
        c.chat([{"role": "user", "content": "nothing recorded"}])


def test_chat_json_rejects_non_json(tmp_path: Path):
    msgs = [{"role": "user", "content": "x"}]
    key = cache_key(EP.model, msgs, None, [])
    (tmp_path / "responses").mkdir()
    (tmp_path / "responses" / f"{key}.json").write_text(json.dumps({"content": "not json"}))
    with pytest.raises(ModelJSONError):
        ModelClient(EP, mock=True, fixtures_dir=tmp_path).chat_json(msgs)


def test_cache_key_changes_with_image_bytes(tmp_path: Path):
    a = tmp_path / "a.png"; a.write_bytes(b"1")
    b = tmp_path / "b.png"; b.write_bytes(b"2")
    m = [{"role": "user", "content": "read"}]
    assert cache_key("m", m, None, [a]) != cache_key("m", m, None, [b])


def test_cache_key_changes_with_extra_but_not_when_empty(tmp_path: Path):
    m = [{"role": "user", "content": "read"}]
    base = cache_key("m", m, None, [])
    assert cache_key("m", m, None, [], extra={"repetition_penalty": 1.1}) != base
    assert cache_key("m", m, None, [], extra=None) == base
    assert cache_key("m", m, None, [], extra={}) == base


def test_chat_full_passes_extra_to_call(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_call(self, messages, json_schema, images, temperature, max_tokens, extra=None):
        seen["extra"] = extra
        return "ok", "stop"

    monkeypatch.setattr(ModelClient, "_call", fake_call)
    c = ModelClient(EP, mock=False, fixtures_dir=tmp_path, record=False)
    c.chat_full([{"role": "user", "content": "x"}], extra={"repetition_penalty": 1.1})
    assert seen["extra"] == {"repetition_penalty": 1.1}


def test_client_for_uses_settings(mini_settings):
    c = client_for(mini_settings, "reader")
    assert c.endpoint.model == "google/medgemma-1.5-4b-it" and c.mock is True


def test_record_writes_fixture_and_replays(tmp_path: Path, monkeypatch):
    calls = []

    def fake_call(self, messages, json_schema, images, temperature, max_tokens, extra=None):
        calls.append(messages)
        return "canned response", "stop"

    monkeypatch.setattr(ModelClient, "_call", fake_call)
    msgs = [{"role": "user", "content": "record me"}]
    key = cache_key(EP.model, msgs, None, [])
    c = ModelClient(EP, mock=True, fixtures_dir=tmp_path, record=True)

    assert c.chat(msgs) == "canned response"
    assert len(calls) == 1
    fixture_path = tmp_path / "responses" / f"{key}.json"
    assert fixture_path.exists()
    assert json.loads(fixture_path.read_text()) == {"model": EP.model, "content": "canned response", "finish_reason": "stop"}

    assert c.chat(msgs) == "canned response"
    assert len(calls) == 1


def test_mock_without_record_never_calls_endpoint(tmp_path: Path, monkeypatch):
    calls = []

    def fake_call(self, messages, json_schema, images, temperature, max_tokens):
        calls.append(messages)
        return "should not be reached", "stop"

    monkeypatch.setattr(ModelClient, "_call", fake_call)
    c = ModelClient(EP, mock=True, fixtures_dir=tmp_path, record=False)
    with pytest.raises(MockMissing):
        c.chat([{"role": "user", "content": "nothing recorded"}])
    assert calls == []


SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}


def _envelope(payload: dict, is_error=False) -> str:
    return json.dumps({"type": "result", "is_error": is_error, "result": json.dumps(payload), "structured_output": payload})


def test_claude_cli_live_call_parses_structured_output(tmp_path: Path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=_envelope({"a": 7}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    c = ClaudeCLI("sonnet", mock=False, fixtures_dir=tmp_path, record=False, timeout_s=9, binary="claude-x")
    assert c.chat_json("sys", "user text", SCHEMA) == {"a": 7}
    cmd = seen["cmd"]
    assert cmd[0] == "claude-x" and "-p" in cmd and cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert cmd[cmd.index("--system-prompt") + 1] == "sys" and cmd[cmd.index("--tools") + 1] == ""
    assert seen["kw"]["input"] == "user text" and seen["kw"]["timeout"] == 9
    assert "user text" not in cmd  # prompt goes over stdin, not argv
    assert Path(seen["kw"]["cwd"]).is_dir() and Path(seen["kw"]["cwd"]).name.startswith("auditpace-claude-")
    c.chat_json("sys", "other text", SCHEMA)
    assert seen["kw"]["cwd"] == c._cwd  # one empty cwd per instance, reused across calls


@pytest.mark.parametrize(
    "returncode,stdout",
    [(1, ""), (0, "not json"), (0, _envelope({"a": 1}, is_error=True)), (0, json.dumps({"type": "result", "result": "x"}))],
)
def test_claude_cli_errors_raise_model_json_error(tmp_path: Path, monkeypatch, returncode, stdout):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom"))
    c = ClaudeCLI("sonnet", mock=False, fixtures_dir=tmp_path, record=False)
    with pytest.raises(ModelJSONError):
        c.chat_json("s", "u", SCHEMA)


def test_claude_cli_timeout_raises(tmp_path: Path, monkeypatch):
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(ModelJSONError, match="timed out"):
        ClaudeCLI("sonnet", mock=False, fixtures_dir=tmp_path, record=False, timeout_s=1).chat_json("s", "u", SCHEMA)


def test_claude_cli_record_then_mock_replay(tmp_path: Path, monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(1)
        return subprocess.CompletedProcess(cmd, 0, stdout=_envelope({"a": 3}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rec = ClaudeCLI("sonnet", mock=True, fixtures_dir=tmp_path, record=True)
    assert rec.chat_json("s", "u", SCHEMA) == {"a": 3}
    assert rec.chat_json("s", "u", SCHEMA) == {"a": 3} and len(calls) == 1  # second call replays
    fx = list((tmp_path / "responses").glob("*.json"))
    assert len(fx) == 1 and json.loads(fx[0].read_text())["model"] == "claude-cli:sonnet"
    mock = ClaudeCLI("sonnet", mock=True, fixtures_dir=tmp_path, record=False)
    assert mock.chat_json("s", "u", SCHEMA) == {"a": 3} and len(calls) == 1
    with pytest.raises(MockMissing):
        mock.chat_json("s", "different", SCHEMA)


def test_chat_full_returns_finish_reason_and_records_it(tmp_path: Path, monkeypatch):
    def fake_call(self, messages, json_schema, images, temperature, max_tokens, extra=None):
        return "partial", "length"

    monkeypatch.setattr(ModelClient, "_call", fake_call)
    msgs = [{"role": "user", "content": "long"}]
    c = ModelClient(EP, mock=True, fixtures_dir=tmp_path, record=True)
    assert c.chat_full(msgs) == ("partial", "length")
    key = cache_key(EP.model, msgs, None, [])
    fx = json.loads((tmp_path / "responses" / f"{key}.json").read_text())
    assert fx == {"model": EP.model, "content": "partial", "finish_reason": "length"}
    replay = ModelClient(EP, mock=True, fixtures_dir=tmp_path, record=False)
    assert replay.chat_full(msgs) == ("partial", "length")
    assert replay.chat(msgs) == "partial"


def test_old_fixture_without_finish_reason_replays_as_stop(tmp_path: Path):
    msgs = [{"role": "user", "content": "old"}]
    key = cache_key(EP.model, msgs, None, [])
    (tmp_path / "responses").mkdir()
    (tmp_path / "responses" / f"{key}.json").write_text(json.dumps({"content": "x"}))
    c = ModelClient(EP, mock=True, fixtures_dir=tmp_path)
    assert c.chat_full(msgs) == ("x", "stop")


def test_build_messages_mime_from_suffix(tmp_path: Path):
    jpg = tmp_path / "p.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    png = tmp_path / "p.png"
    png.write_bytes(b"\x89PNG")
    c = ModelClient(EP, mock=True, fixtures_dir=tmp_path)
    out = c._build_messages([{"role": "user", "content": "see"}], [jpg, png])
    urls = [p["image_url"]["url"] for p in out[-1]["content"] if p["type"] == "image_url"]
    assert urls[0].startswith("data:image/jpeg;base64,")
    assert urls[1].startswith("data:image/png;base64,")


def test_endpoint_serves(monkeypatch):
    import httpx

    from auditpace.models import endpoint_serves

    class R:
        def __init__(self, ids): self._ids = ids
        def raise_for_status(self): pass
        def json(self): return {"data": [{"id": i} for i in self._ids]}

    monkeypatch.setattr(httpx, "get", lambda url, timeout: R(["mock-27b"]))
    assert endpoint_serves(EP) is True
    monkeypatch.setattr(httpx, "get", lambda url, timeout: R(["other"]))
    assert endpoint_serves(EP) is False

    def boom(url, timeout):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", boom)
    assert endpoint_serves(EP) is False
