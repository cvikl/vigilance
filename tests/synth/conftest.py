import json

from auditpace.models import ModelJSONError


class EchoClient:
    """Fake ClaudeCLI: writes each requested document as its must_include strings padded to length.
    `fail_first` makes the first n calls return a document with a fact altered (validation failure);
    `raise_always` raises instead."""

    def __init__(self, fail_first: int = 0, raise_always: bool = False):
        self.calls: list[str] = []
        self.fail_first = fail_first
        self.raise_always = raise_always

    def chat_json(self, system: str, user: str, json_schema: dict) -> dict:
        self.calls.append(user)
        if self.raise_always:
            raise RuntimeError("cli down")
        broken = len(self.calls) <= self.fail_first
        # `user` may have a plain-text retry note appended after the JSON batch (see
        # SynthStage.process); parse only the leading JSON object and ignore the rest.
        body, _ = json.JSONDecoder().raw_decode(user)
        docs = []
        for p in body["patients"]:
            for d in p["documents"]:
                must = list(d["must_include"])
                if broken and must:
                    must[0] = must[0].replace(":", ".")
                pad = " ".join(["Observations stable overnight."] * 30)
                docs.append({"doc_id": d["doc_id"], "text": f"{d['doc_type']} written {d['authored_ts']}. " + " ".join(must) + " " + pad})
        return {"documents": docs}


class FlakyClient:
    """Fake ClaudeCLI simulating transport failures: raises `ModelJSONError` (as `chat_json` does
    on a `claude -p` transport/parse failure) for the first `fail_first` calls (or always, if
    `always_fail`), then delegates to a plain `EchoClient`."""

    def __init__(self, fail_first: int = 0, always_fail: bool = False):
        self.calls: list[str] = []
        self.fail_first = fail_first
        self.always_fail = always_fail
        self._echo = EchoClient()

    def chat_json(self, system: str, user: str, json_schema: dict) -> dict:
        self.calls.append(user)
        if self.always_fail or len(self.calls) <= self.fail_first:
            raise ModelJSONError("simulated transport failure")
        return self._echo.chat_json(system, user, json_schema)
