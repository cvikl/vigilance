"""Build the gateway payload from the real data/processed/ and assert nothing forbidden crosses.
Prints the token-set size, the section list and the per-criterion provisional reasons. No model."""
import re
import sys
from pathlib import Path

import pandas as pd

from auditpace.protocol import load_protocol
from auditpace.report.fmt import printed_tokens
from auditpace.report.gateway import build_payload
from auditpace.settings import load_settings
from auditpace.store import Store

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\b[0-9a-f]{32}\b")
FORBIDDEN = ("quote", "rationale", "justification", "priority_reason", "note", "patient_id", "case_id", "doc_id")


def main() -> int:
    s = load_settings()
    p = load_protocol(Path("protocol.yaml"))
    with Store(s.paths.processed_dir, read_only=True) as store:
        payload, org_map = build_payload(store, p, s, run_id="rpt-00000000T000000-00000000",
                                         now=pd.Timestamp("2026-01-01"), code_sha="unknown",
                                         reporter_model=None, reporter_version=None)
    blob = payload.model_dump_json()
    bad = UUID_RE.findall(blob)
    keys = {k for k in re.findall(r'"([a-z_]+)":', blob)}
    leaks = [k for k in FORBIDDEN if k in keys and k != "caveats_note"]
    print(f"payload: {len(blob):,} bytes; {len(payload.criteria)} criteria; {len(payload.alerts)} alerts; "
          f"{len(org_map)} organisations pseudonymised; {len(printed_tokens(payload))} printed tokens")
    for c in payload.criteria:
        print(f"  {c.id}: n={c.n} reviewed={c.n_reviewed} method={c.method} provisional={c.provisional_reason!r}")
    print(f"reviewers: {payload.quality.reviews.reviewers}; validation: {'present' if payload.validation else 'absent'}")
    if bad or leaks:
        print(f"GATES: FAIL uuids={bad[:3]} leaked_keys={leaks}")
        return 1
    print("GATES: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
