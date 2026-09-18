"""Base class for pipeline stages: idempotent, resumable, quarantine on per-item failure."""
import json
from abc import ABC, abstractmethod
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from auditpace.protocol import Protocol, require_locked
from auditpace.settings import Settings
from auditpace.store import Store


@dataclass
class RunSummary:
    name: str
    n_in: int = 0
    n_out: int = 0
    n_quarantined: int = 0

    def __str__(self) -> str:
        return f"{self.name}: in={self.n_in} out={self.n_out} quarantined={self.n_quarantined}"


class Stage(ABC):
    name: str = "stage"

    def __init__(self, settings: Settings, protocol: Protocol, store: Store):
        self.settings = settings
        self.protocol = protocol
        self.store = store
        self.outputs: list[Any] = []

    @abstractmethod
    def items(self) -> Iterable[Any]: ...

    @abstractmethod
    def process(self, item: Any) -> Any | None: ...

    def is_done(self, item: Any) -> bool:
        return False

    def _attempt(self, item: Any) -> tuple[Any, Any | None, Exception | None]:
        try:
            return item, self.process(item), None
        except Exception as e:  # noqa: BLE001 — per-item failures are quarantined by design
            return item, None, e

    def run(self, limit: int | None = None, force: bool = False, workers: int = 1) -> RunSummary:
        """Process every item (bounded by `limit`), skipping done ones unless `force`.

        With `workers > 1`, `process` runs in a thread pool; results are consumed in item order so
        `outputs` and the quarantine file are identical to a sequential run.
        """
        require_locked(self.protocol)
        self.outputs = []
        qdir = self.store.dir / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        qfile = qdir / f"{self.name}.jsonl"
        summary = RunSummary(self.name)
        items: list[Any] = []
        for i, item in enumerate(self.items()):
            if limit is not None and i >= limit:
                break
            items.append(item)
        summary.n_in = len(items)
        pending = []
        for item in items:
            if not force and self.is_done(item):
                summary.n_out += 1
            else:
                pending.append(item)
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(self._attempt, pending))
        else:
            results = [self._attempt(item) for item in pending]
        with qfile.open("w") as q:
            for item, out, err in results:
                if err is not None:
                    summary.n_quarantined += 1
                    q.write(json.dumps({"item": repr(item), "error": str(err), "type": type(err).__name__}) + "\n")
                    continue
                if out is not None:
                    self.outputs.append(out)
                summary.n_out += 1
        print(summary, flush=True)
        return summary
