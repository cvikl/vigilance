"""Cohort selection: apply the protocol's cohort rule, then a seeded stratified sample."""
from datetime import timedelta

import numpy as np
import pandas as pd

from auditpace.cohort.source import SyntheaSource
from auditpace.protocol import CohortRule

ICU_CODE = 305351004  # fallback default; callers should pass the protocol's icu event code


def _eligible(src: SyntheaSource, rule: CohortRule, icu_code: int) -> pd.DataFrame:
    codes = ",".join(f"'{c}'" for c in rule.include["condition_snomed"])
    classes = rule.require_any.get("encounter_class", ["inpatient"])
    cls = ",".join(f"'{c}'" for c in classes)
    cov_period = ""
    req_period = ""
    if rule.period:
        # Exclusive upper bound (end + 1 day) so timed encounters on the last day of the
        # period aren't excluded by a cast-to-midnight comparison against the end date.
        end_excl = rule.period["end"] + timedelta(days=1)
        cov_period = f" and c.START >= '{rule.period['start']}' and c.START < '{end_excl}'"
        req_period = f" and e.START >= '{rule.period['start']}' and e.START < '{end_excl}'"
    return src.sql(
        f"""
        with cov as (select distinct PATIENT from conditions c where CODE in ({codes}){cov_period}),
             req as (select distinct PATIENT from encounters e where ENCOUNTERCLASS in ({cls}){req_period}),
             icu as (select distinct PATIENT from encounters where CODE = '{icu_code}')
        select p.Id as patient_id, p.BIRTHDATE as birthdate, p.DEATHDATE as deathdate,
               p.GENDER as sex, p.RACE as race, p.ETHNICITY as ethnicity,
               (i.PATIENT is not null) as icu, (p.DEATHDATE is not null) as died
        from patients p
        join cov on cov.PATIENT = p.Id
        join req on req.PATIENT = p.Id
        left join icu i on i.PATIENT = p.Id
        order by p.Id
        """
    )


def select_patients(src: SyntheaSource, rule: CohortRule, icu_code: int = ICU_CODE) -> pd.DataFrame:
    df = _eligible(src, rule, icu_code)
    n = rule.sample.n
    if len(df) <= n:
        return df.reset_index(drop=True)
    rng = np.random.default_rng(rule.sample.seed)
    strata = rule.sample.stratify_by or []
    if not strata:
        idx = rng.choice(len(df), size=n, replace=False)
        return df.iloc[np.sort(idx)].reset_index(drop=True)
    key = df[strata].astype(str).agg("|".join, axis=1)
    sizes = key.value_counts()
    if len(sizes) > n:
        raise ValueError(f"sample n={n} smaller than number of non-empty strata {len(sizes)}")
    alloc = {k: max(1, round(n * v / len(df))) for k, v in sizes.items()}
    # fix rounding so total == n (trim largest strata first)
    while sum(alloc.values()) > n:
        k = max(alloc, key=lambda k: alloc[k])
        alloc[k] -= 1
    while sum(alloc.values()) < n:
        k = max(sizes.index, key=lambda k: sizes[k] - alloc[k])
        alloc[k] += 1
    picks = []
    for k, m in alloc.items():
        members = np.flatnonzero(key.values == k)
        picks.extend(rng.choice(members, size=min(m, len(members)), replace=False))
    return df.iloc[np.sort(picks)].reset_index(drop=True)
