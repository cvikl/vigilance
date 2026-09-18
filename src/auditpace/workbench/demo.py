"""Held-back arrivals for the pitch: case ids listed under `## held` in `docs/demo_cases.txt` are
hidden from the queue when the server starts and released one at a time by `POST /demo/release`
(the demo panel's `n` key). Nothing is adjudicated live — the verdicts already exist; only their
visibility changes. `POST /demo/reset` re-holds every released case so a rehearsal can repeat."""
import time
from dataclasses import dataclass, field
from pathlib import Path

DEMO_CASES = Path("docs/demo_cases.txt")
HELD_HEADER = "## held"


def read_held(path: Path = DEMO_CASES) -> list[str]:
    """Case ids under the `## held` header, in file order; [] when the file or header is absent."""
    if not path.exists():
        return []
    held, on = [], False
    for ln in path.read_text().splitlines():
        s = ln.strip()
        if s.startswith("## "):
            on = s.lower().startswith(HELD_HEADER)
            continue
        if on and s and not s.startswith("#"):
            held.append(s)
    return held


@dataclass
class Arrivals:
    """Release order is list order; `released` maps case id → release time (for the 'new' highlight)."""
    held: list[str] = field(default_factory=list)
    released: dict[str, float] = field(default_factory=dict)
    version: int = 0

    def pending(self) -> list[str]:
        return [c for c in self.held if c not in self.released]

    def hidden(self) -> set[str]:
        return set(self.pending())

    def release(self) -> str | None:
        nxt = self.pending()
        if not nxt:
            return None
        self.released[nxt[0]] = time.time()
        self.version += 1
        return nxt[0]

    def reset(self) -> None:
        self.released.clear()
        self.version += 1

    def is_new(self, case_id: str, within_s: float = 60.0) -> bool:
        t = self.released.get(case_id)
        return t is not None and (time.time() - t) <= within_s
