"""System prompt, batch prompt and output schema for document authoring (S2 design §7)."""
import hashlib
import json

import pandas as pd

from auditpace.synth.facts import time_text
from auditpace.synth.plan import DocSpec

EVENT_LABELS = {
    "suspected": "COVID-19 suspected; swab sample taken",
    "confirmed": "positive SARS-CoV-2 PCR result reported",
    "hypoxaemia": "hypoxaemia recorded (SpO2 below 92% on air)",
    "admitted": "admitted to hospital",
    "icu": "admitted to the intensive care unit",
    "ventilated": "invasive ventilation started",
    "enoxaparin": "enoxaparin first dose given",
    "discharged": "discharged from hospital",
    "follow_up": "seen in follow-up clinic",
}

SYSTEM_PROMPT = """You write realistic synthetic NHS clinical documents for a data-quality project. Every patient is fictional; the pathway facts you are given are the only truth.

Setting: an acute NHS hospital in England, spring 2020, COVID-19 admission pathway. Write in UK clinical register: NEWS2, SpO2, RR, HR, BP, ABG, CXR, CPAP, ITU/ICU, AMU, SHO, SpR, FY1, TTO, GP, tds, od, bd, mmol/L, kPa, paracetamol, adrenaline, 24-hour clock, dates as DD/MM/YYYY. Never use US terms (ER, attending physician, resident physician, intern, acetaminophen, Tylenol, EKG, epinephrine, mg/dL, Foley, code status, nurse practitioner).

Input is JSON: a list of patients, each with documents to write. For each document you are told:
- doc_type and authored_ts (when it was written);
- known_events: the pathway events that had happened by authored_ts, with a label and the exact time string. Mention only these; never refer to anything that happens later (no ICU in an ED clerking if ICU is not listed);
- must_include: strings that must appear verbatim, character for character, somewhere natural in the text (time strings such as "14:20 on 12/03/2020" and whole sentences). Do not alter punctuation, spacing or wording inside them; you may continue a sentence after a must_include string's final word, but never reword, reorder or split the words inside it. Every other clinical detail (observations, bloods, drugs, history, plan) you invent, plausible for COVID-19 and the age band, consistent across the patient's documents;
- died: if a date is given, the patient died on that date; a discharge_summary authored after death is a death summary.

Document styles (100-350 words each):
- lab_report: virology report — sample type, collected/received/reported times, result, comment line.
- ed_clerking: ED clerking — presenting complaint, history, observations with times, examination, impression, plan including admission decision and VTE assessment.
- ward_round: consultant ward round entry — day of admission, observations, bloods, VTE prophylaxis status, escalation status, plan.
- icu_note: ICU admission/daily note — reason for admission with times, respiratory support, ventilation details, organ support, plan.
- discharge_summary: discharge summary — admission and discharge dates/times, diagnosis, course, medication changes, follow-up arrangements (respiratory clinic review within 2 weeks of discharge), GP actions.
- clinic_letter: post-discharge clinic letter to the GP — dates of discharge and attendance, current symptoms, investigations, plan.

Do not use patient names, NHS numbers or real hospital names; refer to "the patient". Output JSON only, matching the schema: {"documents":[{"doc_id":"<as given>","text":"<document>"}]} with one entry per requested document and no extras.
"""

PROMPT_VERSION = "synth-" + hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "documents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"doc_id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["doc_id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["documents"],
    "additionalProperties": False,
}


def _alias_doc_id(alias: str, spec: DocSpec) -> str:
    return f"{alias}:{spec.doc_type}"


def build_user_prompt(plans: list[tuple[pd.Series, list[DocSpec]]]) -> tuple[str, dict[str, DocSpec]]:
    """JSON batch prompt with P1..Pn aliases; returns (prompt, {alias_doc_id: spec})."""
    patients = []
    planned: dict[str, DocSpec] = {}
    for n, (patient, specs) in enumerate(plans, start=1):
        alias = f"P{n}"
        docs = []
        for s in specs:
            aid = _alias_doc_id(alias, s)
            if aid in planned:
                raise ValueError(f"duplicate document {aid} for alias {alias}")
            planned[aid] = s
            must = list(dict.fromkeys(f.text for f in s.facts))
            docs.append({
                "doc_id": aid,
                "doc_type": s.doc_type,
                "authored_ts": s.authored_ts.strftime("%Y-%m-%dT%H:%M"),
                "known_events": [{"event": e, "label": EVENT_LABELS.get(e, e), "when": time_text(t)} for e, t in s.known_events],
                "must_include": must,
            })
        died = specs[0].died if specs else None
        patients.append({
            "alias": alias,
            "age_band": str(patient.age_band),
            "sex": str(patient.sex),
            "died": died.strftime("%d/%m/%Y") if died is not None else None,
            "documents": docs,
        })
    return json.dumps({"patients": patients}, indent=1), planned
