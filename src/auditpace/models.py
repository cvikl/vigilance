"""OpenAI-compatible chat client (vLLM) with record/replay so tests need no GPU."""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

import httpx

from auditpace.settings import ModelEndpoint, Settings

Role = Literal["adjudicator", "reader", "designer", "reporter"]


class MockMissing(FileNotFoundError):
    pass


class ModelJSONError(ValueError):
    pass


def cache_key(
    model: str, messages: list[dict], json_schema: dict | None, images: list[Path], extra: dict | None = None
) -> str:
    """Key covers model, messages, schema, image bytes and (when non-empty) `extra` — temperature/
    max_tokens are deliberately excluded so a prompt has one fixture; callers needing distinct
    samples must vary the prompt or `extra`. `extra=None`/`{}` hashes identically to omitting it,
    so every fixture recorded before `extra` existed keeps its key."""
    h = hashlib.sha256()
    payload = {"model": model, "messages": messages, "schema": json_schema}
    if extra:
        payload["extra"] = extra
    h.update(json.dumps(payload, sort_keys=True).encode())
    for p in images:
        h.update(Path(p).read_bytes())
    return h.hexdigest()


class ModelClient:
    def __init__(self, endpoint: ModelEndpoint, mock: bool, fixtures_dir: Path, record: bool | None = None):
        self.endpoint = endpoint
        self.mock = mock
        self.record = record if record is not None else os.environ.get("AUDITPACE_RECORD") == "1"
        self.responses_dir = Path(fixtures_dir) / "responses"

    def _fixture(self, key: str) -> Path:
        return self.responses_dir / f"{key}.json"

    @staticmethod
    def _mime(p: Path) -> str:
        return "image/jpeg" if Path(p).suffix.lower() in (".jpg", ".jpeg") else "image/png"

    def _build_messages(self, messages: list[dict], images: list[Path]) -> list[dict]:
        if not images:
            return messages
        parts = [{"type": "text", "text": messages[-1]["content"]}]
        for p in images:
            b64 = base64.b64encode(Path(p).read_bytes()).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:{self._mime(p)};base64,{b64}"}})
        return messages[:-1] + [{"role": messages[-1]["role"], "content": parts}]

    def _call(
        self,
        messages: list[dict],
        json_schema: dict | None,
        images: list[Path],
        temperature: float,
        max_tokens: int,
        extra: dict | None = None,
    ) -> tuple[str, str]:
        """POST one chat completion. `extra` (e.g. {"repetition_penalty": 1.3}) is applied via
        `body.update(extra)` after the standard fields (model, messages, temperature, max_tokens,
        response_format) are set, so a key in `extra` overrides the corresponding standard field
        instead of being dropped by it — deliberate, not an oversight."""
        body: dict = {
            "model": self.endpoint.model,
            "messages": self._build_messages(messages, images),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": json_schema}}
        if extra:
            body.update(extra)
        r = httpx.post(
            f"{self.endpoint.base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self.endpoint.api_key}"},
            timeout=600,
        )
        r.raise_for_status()
        choice = r.json()["choices"][0]
        return choice["message"]["content"], choice.get("finish_reason") or "stop"

    def chat_full(
        self,
        messages: list[dict],
        *,
        json_schema: dict | None = None,
        images: list[Path] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        extra: dict | None = None,
    ) -> tuple[str, str]:
        """Return (content, finish_reason). finish_reason is "stop" or "length" (vLLM); fixtures
        recorded before S4 lack the key and replay as "stop". `extra` (e.g. {"repetition_penalty":
        1.1}) is merged into the request body and folded into the fixture key when non-empty;
        it is applied after the standard fields in `_call` and may override them (deliberate)."""
        images = images or []
        key = cache_key(self.endpoint.model, messages, json_schema, images, extra)
        fx = self._fixture(key)
        if self.record:
            if fx.exists():
                return self._replay(fx)
            content, finish = self._call(messages, json_schema, images, temperature, max_tokens, extra)
            fx.parent.mkdir(parents=True, exist_ok=True)
            fx.write_text(json.dumps({"model": self.endpoint.model, "content": content, "finish_reason": finish}, indent=1))
            return content, finish
        if self.mock:
            if not fx.exists():
                raise MockMissing(f"no recorded response for key {key}; run with AUDITPACE_RECORD=1")
            return self._replay(fx)
        return self._call(messages, json_schema, images, temperature, max_tokens, extra)

    @staticmethod
    def _replay(fx: Path) -> tuple[str, str]:
        d = json.loads(fx.read_text())
        return d["content"], d.get("finish_reason", "stop")

    def chat(self, messages: list[dict], **kw) -> str:
        return self.chat_full(messages, **kw)[0]

    def chat_json(self, messages: list[dict], **kw) -> dict:
        raw = self.chat(messages, **kw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ModelJSONError(f"model returned non-JSON: {raw[:200]!r}") from e


def client_for(settings: Settings, role: Role) -> ModelClient:
    ep = getattr(settings.models, role)
    if ep is None:
        raise ValueError(f"no endpoint configured for role {role!r} in config.yaml")
    return ModelClient(ep, mock=settings.mock, fixtures_dir=settings.paths.fixtures_dir)


def endpoint_serves(ep: ModelEndpoint, timeout: float = 5.0) -> bool:
    """True when `GET {base_url}/models` answers and lists `ep.model`."""
    try:
        r = httpx.get(f"{ep.base_url}/models", timeout=timeout)
        r.raise_for_status()
        return ep.model in [m["id"] for m in r.json().get("data", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return False


class ClaudeCLI:
    """`claude -p` wrapper with the same record/replay contract as ModelClient (ADR 0003).

    The user prompt goes over stdin (batches exceed comfortable argv sizes); the system prompt
    replaces the CLI default; `--tools ""` disables tool use; `--json-schema` makes the CLI return
    a parsed `structured_output`. Runs in an empty temp cwd (created once per instance, reused
    for every call) so no project CLAUDE.md leaks into context; the user-level `~/.claude/CLAUDE.md`
    still loads.
    """

    def __init__(self, model: str, mock: bool, fixtures_dir: Path, record: bool | None = None,
                 timeout_s: int = 600, binary: str = "claude"):
        self.model = model
        self.mock = mock
        self.record = record if record is not None else os.environ.get("AUDITPACE_RECORD") == "1"
        self.responses_dir = Path(fixtures_dir) / "responses"
        self.timeout_s = timeout_s
        self.binary = binary
        self._cwd: str | None = None

    @property
    def model_tag(self) -> str:
        return f"claude-cli:{self.model}"

    def _fixture(self, key: str) -> Path:
        return self.responses_dir / f"{key}.json"

    def _call(self, system: str, user: str, json_schema: dict) -> dict:
        cmd = [self.binary, "-p", "--model", self.model, "--output-format", "json",
               "--json-schema", json.dumps(json_schema), "--tools", "", "--system-prompt", system]
        if self._cwd is None or not os.path.isdir(self._cwd):
            self._cwd = tempfile.mkdtemp(prefix="auditpace-claude-")
        try:
            r = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=self.timeout_s, cwd=self._cwd, check=False)
        except subprocess.TimeoutExpired as e:
            raise ModelJSONError(f"claude -p timed out after {self.timeout_s}s") from e
        if r.returncode != 0:
            raise ModelJSONError(f"claude -p exit {r.returncode}: {r.stderr[:500]!r}")
        try:
            env = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise ModelJSONError(f"claude -p returned non-JSON: {r.stdout[:200]!r}") from e
        if env.get("is_error") or not isinstance(env.get("structured_output"), dict):
            raise ModelJSONError(f"claude -p error: {str(env.get('result', ''))[:300]!r}")
        return env["structured_output"]

    def chat_json(self, system: str, user: str, json_schema: dict) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        key = cache_key(self.model_tag, messages, json_schema, [])
        fx = self._fixture(key)
        if self.record:
            if fx.exists():
                return json.loads(json.loads(fx.read_text())["content"])
            out = self._call(system, user, json_schema)
            fx.parent.mkdir(parents=True, exist_ok=True)
            fx.write_text(json.dumps({"model": self.model_tag, "content": json.dumps(out)}, indent=1))
            return out
        if self.mock:
            if not fx.exists():
                raise MockMissing(f"no recorded response for key {key}; run with AUDITPACE_RECORD=1")
            return json.loads(json.loads(fx.read_text())["content"])
        return self._call(system, user, json_schema)
