"""Print document stats and check planted-fact coverage. Run after `auditpace synth`."""
import json
import sys

import pandas as pd

from auditpace.protocol import load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store
from auditpace.synth.validate import BANLIST, fact_needle

s, p = load_settings(), load_protocol()
with Store(s.paths.processed_dir) as store:
    docs = store.read("documents")
    cases = store.read("cases")
    pats = store.read("patients")
print(f"documents={len(docs)} patients_covered={docs.patient_id.nunique()}/{len(pats)}")
print(docs.doc_type.value_counts().to_string(), "\n")
words = docs.text.str.split().str.len()
print(f"words: min={words.min()} median={int(words.median())} max={words.max()}")
print(f"handwritten share of notes: {docs[docs.doc_type.isin(['ed_clerking', 'ward_round'])]["style"].eq('handwritten').mean():.2f}")
facts = [(d.doc_id, d.text, f) for d in docs.itertuples() for f in json.loads(d.planted_facts)]
bad = []
not_verbatim = [(doc, f["fact_id"]) for doc, text, f in facts if fact_needle(f["text"]) not in text]
if not_verbatim:
    bad.append(f"{len(not_verbatim)} facts not verbatim, e.g. {not_verbatim[:3]}")
ban = docs[docs.text.str.contains(BANLIST)]
if len(ban):
    bad.append(f"{len(ban)} documents with US-register terms, e.g. {list(ban.doc_id[:3])}")
authored = set(docs.patient_id)
cases = cases.merge(pats[["patient_id", "deathdate"]], on="patient_id")
documentable = cases.deathdate.isna() | (cases.end_ts <= cases.deathdate.dt.normalize() + pd.Timedelta(hours=23, minutes=59))
for c in p.criteria:
    d = cases[(cases.criterion_id == c.id) & cases.applies & cases.end_ts.notna() & cases.patient_id.isin(authored) & documentable]
    times = {f["case_id"] for _, _, f in facts if f["kind"] == "time"}
    reasons = {f["case_id"] for _, _, f in facts if f["kind"] == "reason"}
    distract = {f["case_id"] for _, _, f in facts if f["kind"] == "distractor"}
    n_t = d.case_id.isin(times).sum()
    n_r = d[d.breached].case_id.isin(reasons).sum()
    n_d = d[~d.breached].case_id.isin(distract).sum()
    print(f"{c.id} measured={len(d):5d} time_facts={n_t:5d} breached={int(d.breached.sum()):4d} reason_facts={n_r:4d} distractors={n_d:4d}")
    if n_t != len(d) or n_r != d.breached.sum():
        bad.append(f"{c.id}: fact coverage incomplete")
if bad:
    print("PROBLEMS:", *bad, sep="\n  ")
    sys.exit(1)
print("ok")
