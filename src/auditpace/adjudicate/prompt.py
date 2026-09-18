"""System prompt, per-criterion reply schema and reply model for adjudication (S5 design §4).

Event glosses are deliberately a superset of, not an import from, synth.prompt.EVENT_LABELS (plus
`died`, a protocol event that is never a criterion endpoint): a synth wording change must not
silently move prompt_version (R11). Reason codes are shown with a short
gloss each (REASON_GLOSS) written in words of its own: the reasons.yaml / distractors.yaml phrasings
are planted facts and never enter this prompt (tests/adjudicate/test_prompt.py checks no shared
4-token run).
"""
from dataclasses import dataclass
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from auditpace.protocol import Criterion

EVENT_GLOSS: dict[str, str] = {
    # Iteration 1 (task 7): ED clerking writes the swab time without its date ("at 17:12; ... reported
    # 18:46 on 05/03/2020") and the model quoted it, so parse_time_quote took the wrong time; steer
    # to the lab report line, which always carries the full string.
    "suspected": "COVID-19 suspected; swab sample taken (the lab report's 'Sample collected' time)",
    "confirmed": "positive SARS-CoV-2 PCR result reported (the lab report's 'Reported' time, not sample collection or receipt)",
    "hypoxaemia": "hypoxaemia recorded (SpO2 below 92% on air)",
    # Iteration 2 (task 7): an iteration-1 parenthetical here ("ward or AMU admission from ED; not the
    # ICU") made the model abstain because no document "explicitly stated" that phrase — keep it plain.
    "admitted": "admitted to hospital",
    "icu": "admitted to the intensive care unit",
    "ventilated": "invasive ventilation started",
    "enoxaparin": "enoxaparin first dose given",
    "discharged": "discharged from hospital",
    "follow_up": "seen in follow-up clinic",
    "died": "patient died (date of death recorded)",
}

# Iteration 1 (task 7): 8/27 recorded replies hit finish_reason=length in a whitespace loop straight
# after `"evidence": []` — the prompt described only five fields, so the model tried to close the
# object where the schema demands confidence + rationale. Step 4 and the closing field list name
# every field in schema order; "compact single-line" removes the indentation the loop was made of.
# Also: 4 replies returned null times while stating them in the rationale ("in multiple documents"),
# so step 1 now says repetition across documents is expected and null is for absent times only.
# Iteration 2 (task 7): iteration 1 fixed the loop (23/23 stop) but every reply returned null times,
# rationales citing the literal template ("not documented in the required format 'HH:MM on
# DD/MM/YYYY'"); the template mention is gone and a worked example of a filled reply now anchors the
# from_time/to_time object shape.
# Iteration 3 (task 7): the iteration-2 example's evidence quote was a reasons.yaml planted phrasing
# (drug_shortage line 1) — planted facts must never enter this prompt (module docstring) — so the
# example now uses an invented, non-planted passage; gates were already passing.
# Iteration 4 (task 7): reason accuracy on breached rows was 1/7 — the model called not_breached on
# four over-target cases because it judged attribution ("patient choice, not a system failure") and
# so gave no reason, and it picked "other" over a matching listed code; step 2 now says the call is
# arithmetic alone and step 3 says "other" is for when no listed code fits.
# Task 7 follow-up (controller ruling): reply_schema now generates rationale before status, and step 2
# makes the rationale restate both times and the elapsed hours, so the call is made after the
# arithmetic (mini: the model called not_breached on 4/6 breaches, then computed an over-target gap).
# Step 4 decouples the reason from the call: 5/7 breached mini rows lost their reason_tag because the
# model's own call was not "breached"; the stage (R9) drops reason_tag when the computed status is not
# breached, so the model always reports a described cause of delay. The "resolved delay" sentence is
# reworded so it no longer tells the model to withhold the reason code.
# Task 7 follow-up, recording 2: with rationale first the model computed the hours correctly but still
# wrote "7.17 hours, within the 4-hour target" on three H2 breaches (copying the example's phrase
# rather than comparing), so step 2 demands an explicit inequality; it also copied the example's
# "other" (and its rationale wording) onto a case whose evidence matched a listed code, so the example
# now says "other" is a last resort; and it quoted one two-time ED sentence for both events on two
# cases (stage guard → abstain), so step 1 requires two different, shortest passages.
# Task 7 follow-up, recording 3: two H6 replies copied the example's "<patient>" placeholder verbatim
# as doc_id (4 unfound time quotes), so the example uses a realistic dummy id and says where doc_id
# comes from; step 4 says an indirectly described cause still counts (REASON_GLOSS above).
# Review round 1: step-4 examples and the worked example reworded (they echoed planted phrasings;
# the example evidence now fits no H4 code, so "other" is shown used correctly); the step-2 comparison
# is in words because the model copied the quoted "x hours > y hours" templates literally.
# Task 7 follow-up, recording 3: the model reported "no cause of delay described" on breaches whose
# planted cause is narrated indirectly (a reluctant patient, a referral re-sent, a late escalation) —
# the bare codes did not cue it — so each criterion's codes are glossed in the user prompt. Own
# neutral wording; never a reasons.yaml sentence (planted phrasings must not enter the prompt; the
# test checks no 4-token run is shared with any planted or distractor phrase). Review round 1: every
# gloss reworded — several were planted sentences minus a clause (R11 leak). Review round 2: four more
# reworded from a different angle (they kept a planted variant's noun+verb pair in the same order).
REASON_GLOSS: dict[str, dict[str, str]] = {
    "H1": {
        "swab_delay": "getting the swab done took longer than it should",
        "lab_backlog": "the lab was slow to run or report the test",
        "result_not_actioned": "the answer was back but nobody picked it up",
        "other": "a cause not listed above",
    },
    "H2": {
        "bed_unavailable": "there was nowhere on a ward to put the patient",
        "referral_not_received": "the admitting doctors never got the request to take the patient",
        "patient_declined": "the patient was unwilling to stay at first",
        "transport_delay": "getting the patient physically to the ward took too long",
        "other": "a cause not listed above",
    },
    "H3": {
        "icu_full": "critical care had nowhere to put the patient",
        "escalation_delayed": "critical care was asked for later than it should have been",
        "news2_not_recorded": "the early-warning score was not being charted, so nobody saw the patient getting worse",
        "other": "a cause not listed above",
    },
    "H4": {
        "not_prescribed": "nobody wrote the dose up to begin with",
        "prescription_unsigned": "a missing signature meant the nurses would not give it",
        "contraindication_documented": "it was held back on purpose for a stated medical concern",
        "drug_shortage": "the ward had run out of it",
        "other": "a cause not listed above",
    },
    "H5": {
        "ventilator_unavailable": "critical care had no spare breathing support",
        "decision_delayed": "the go-ahead for a breathing tube was slow to come",
        "other": "a cause not listed above",
    },
    "H6": {
        "not_booked": "no clinic slot was ever set up",
        "dna": "the patient failed to turn up",
        "lost_to_follow_up": "nobody could reach the patient after they went home",
        "other": "a cause not listed above",
    },
}

SYSTEM_PROMPT = """You are a clinical audit adjudicator for an NHS hospital. You are given the OCR transcripts of one patient's clinical documents and one audit criterion of the form "time from event A to event B must be within a target". Transcripts may contain OCR errors. The first lines of each document (hospital name, Hospital No, Doc:, a date) are page letterhead, not clinical evidence.

Do exactly this:
1. Find the time at which event A happened and the time at which event B happened, as written in the documents. Copy each full time-and-date string character-for-character as it appears, for example "14:20 on 12/03/2020" (never the time alone), together with the doc_id of the document you read it from. If a sentence gives the time without its date, quote a different passage or document that gives both. The same event time is normally repeated in several documents — that is expected: quote it from any one of them and give that document's doc_id. Return null for a time only if it is written in none of the documents; if you can state the time in your rationale, you must return it in from_time or to_time. Quote from_time and to_time from two different passages, each the shortest span that contains that event's time and date; never the same passage for both.
2. In rationale, first restate the two times you found, then the elapsed hours as a number, then say in words whether that number is greater than the target number of hours or not, then your call: greater than the target is breached.
3. Give your own call from the arithmetic alone: "breached" if B happened more than the target number of hours after A (whatever the reason for the delay, including the patient's own choice), "not_breached" if within the target, "abstain" if either time is not documented.
4. Whatever your call, if the documents describe a cause of delay between event A and event B, give the ONE reason code from the list that best fits it ("other" if none fits) and quote up to three verbatim passages that support it, each with its doc_id. A cause may be described indirectly — a patient who was unwilling to stay, a request that went astray, a review that came late — and still counts. Quotes must be copied exactly from the transcript: never paraphrase, never merge sentences. If the documents describe no cause of delay, return null for the reason and an empty evidence list.
5. Give a confidence between 0 and 1.

A described delay does not by itself make the call "breached": the call comes from the elapsed hours against the target only. Do not infer a breach from silence.

Return only compact single-line JSON (no indentation) with exactly these fields in this order: from_time, to_time, rationale, status, reason_tag, evidence, confidence. Example of a complete reply for a different patient whose admission-to-enoxaparin target of 24 hours was breached; doc_id is copied exactly from the "### Document …" heading of the document you quote:
{"from_time":{"doc_id":"3f9c2a1e-0000-4000-8000-000000000001:ed_clerking","quote":"Admitted to hospital at 14:20 on 12/03/2020"},"to_time":{"doc_id":"3f9c2a1e-0000-4000-8000-000000000001:ward_round","quote":"Enoxaparin first dose given 09:05 on 14/03/2020"},"rationale":"Admitted 14:20 on 12/03/2020, first dose 09:05 on 14/03/2020: 42.75 hours, which is greater than the 24-hour target, so breached; the ward round gives a cause.","status":"breached","reason_tag":"other","evidence":[{"doc_id":"3f9c2a1e-0000-4000-8000-000000000001:ward_round","quote":"Electronic prescribing system offline across the trust overnight; paper charts issued the next morning."}],"confidence":0.9}
In this example "other" is used because a system outage matches none of the listed codes; whenever a listed code fits the described cause, use that code. For a case that is not breached, from_time and to_time are still filled; reason_tag and evidence are still given if the documents describe a cause of delay, otherwise null and []."""

USER_TEMPLATE = """Criterion {id} — {name}
Event A (from): {from_event} — {from_gloss}
Event B (to): {to_event} — {to_gloss}
Target: B within {target} hours of A
Standard: {standard}
Reason codes:
{reasons}

{documents}"""

DOC_TEMPLATE = "### Document {doc_id} ({doc_type}, authored {authored})\n{text}"
_TS = "%H:%M on %d/%m/%Y"   # same format the documents use for event times


@dataclass(frozen=True)
class DocText:
    doc_id: str
    doc_type: str
    authored_ts: pd.Timestamp
    text: str


def build_messages(criterion: Criterion, docs: list[DocText]) -> list[dict]:
    body = "\n\n".join(
        DOC_TEMPLATE.format(doc_id=d.doc_id, doc_type=d.doc_type, authored=d.authored_ts.strftime(_TS), text=d.text)
        for d in sorted(docs, key=lambda d: (d.authored_ts, d.doc_id))
    )
    user = USER_TEMPLATE.format(
        id=criterion.id, name=criterion.name,
        from_event=criterion.from_, from_gloss=EVENT_GLOSS.get(criterion.from_, criterion.from_),
        to_event=criterion.to, to_gloss=EVENT_GLOSS.get(criterion.to, criterion.to),
        target=f"{criterion.target_hours:g}", standard=criterion.standard,
        reasons="\n".join(f"- {r}: {REASON_GLOSS.get(criterion.id, {}).get(r, r)}" for r in criterion.reasons),
        documents=body,
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def reply_schema(criterion: Criterion) -> dict:
    cite = {"type": "object", "properties": {"doc_id": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["doc_id", "quote"], "additionalProperties": False}
    # Property order is generation order under vLLM guided decoding: rationale (both times + elapsed
    # hours) comes before status so the model computes before it commits. With status first, the
    # mini 27B replies called not_breached on 4/6 breaches and then wrote "5.68 hours, within the
    # 4-hour target" in the rationale (task 7 follow-up).
    return {
        "type": "object",
        "properties": {
            "from_time": {"anyOf": [cite, {"type": "null"}]},
            "to_time": {"anyOf": [cite, {"type": "null"}]},
            "rationale": {"type": "string"},
            "status": {"type": "string", "enum": ["breached", "not_breached", "abstain"]},
            "reason_tag": {"type": ["string", "null"], "enum": [*criterion.reasons, None]},
            "evidence": {"type": "array", "items": cite, "maxItems": 3},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["from_time", "to_time", "rationale", "status", "reason_tag", "evidence", "confidence"],
        "additionalProperties": False,
    }


class Cite(BaseModel):
    doc_id: str
    quote: str


class Reply(BaseModel):
    from_time: Cite | None = None
    to_time: Cite | None = None
    status: Literal["breached", "not_breached", "abstain"]
    reason_tag: str | None = None
    evidence: list[Cite] = Field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""
