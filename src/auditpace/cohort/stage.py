"""Stage 1: cohort → patients, events, cases (+ completeness report)."""
import pandas as pd

from auditpace.cohort.cases import build_cases
from auditpace.cohort.events import derive_events, drop_post_mortem, organisation_of
from auditpace.cohort.plant import plant_timeline
from auditpace.cohort.select import select_patients
from auditpace.cohort.source import SyntheaSource
from auditpace.stage import Stage

_BANDS = [(0, 17, "0-17"), (18, 39, "18-39"), (40, 59, "40-59"), (60, 79, "60-79"), (80, None, "80+")]


def age_band(birthdate: pd.Timestamp, at: pd.Timestamp) -> str:
    if pd.isna(birthdate) or pd.isna(at):
        raise ValueError(f"age_band: invalid birthdate={birthdate} at={at}")
    years = int((at - birthdate).days // 365.25)
    if years < 0:
        raise ValueError(f"age_band: invalid birthdate={birthdate} at={at}")
    return next(b for lo, hi, b in _BANDS if lo <= years and (hi is None or years <= hi))


def _first_code(code: int | list[int]) -> int:
    return code[0] if isinstance(code, list) else code


def anchor_dates(events: pd.DataFrame) -> pd.Series:
    """Per-patient anchor timestamp for `age_band`: `admitted` event ts, else the patient's
    earliest event ts (controller ruling — every cohort patient has >=1 event, so this always
    resolves).
    """
    admitted = events.loc[events.event_type == "admitted"].set_index("patient_id").ts
    earliest = events.sort_values("ts").groupby("patient_id").ts.first()
    return admitted.combine_first(earliest)


class CohortStage(Stage):
    name = "cohort"

    def __init__(self, settings, protocol, store, limit_n: int | None = None):
        super().__init__(settings, protocol, store)
        self.limit_n = limit_n

    def items(self):
        return ["cohort"]

    def is_done(self, item) -> bool:
        return all(self.store.exists(t) for t in ("patients", "events", "cases"))

    def process(self, item):
        p = self.protocol
        src = SyntheaSource(self.settings.paths.synthea_dir)
        rule = p.cohort.model_copy(deep=True)
        if self.limit_n:
            rule.sample.n = min(rule.sample.n, self.limit_n)
        pats = select_patients(src, rule, icu_code=_first_code(p.events["icu"].code))
        ids = list(pats.patient_id)
        events = derive_events(src, p.events, ids)
        events = drop_post_mortem(events, pats)
        org = organisation_of(src, ids, admitted_code=_first_code(p.events["admitted"].code))
        cases = build_cases(events, p.criteria)
        events, cases = plant_timeline(events, cases, p.criteria, p.synthetic, seed=rule.sample.seed)

        anchor = anchor_dates(events)
        pats = pats.merge(org, on="patient_id", how="left")
        pats["age_band"] = [
            age_band(pd.Timestamp(b), pd.Timestamp(anchor.loc[pid])) for b, pid in zip(pats.birthdate, pats.patient_id)
        ]
        pats = pats[["patient_id", "age_band", "sex", "race", "ethnicity", "organization_id", "icu", "died", "birthdate", "deathdate"]]

        have = events.groupby("event_type").patient_id.nunique()
        comp = pd.DataFrame(
            {"event_type": list(p.events), "n_patients_with": [int(have.get(e, 0)) for e in p.events]}
        )
        comp["n_patients_without"] = len(pats) - comp.n_patients_with

        h = p.hash
        self.store.write("patients", pats, h)
        self.store.write("events", events, h)
        self.store.write("cases", cases, h)
        self.store.write("cohort_completeness", comp, h)
        print("cohort_completeness:\n" + comp.to_string(index=False), flush=True)
        return {"patients": len(pats), "cases": len(cases)}
