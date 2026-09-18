"""Extract 5 COVID inpatients (incl. 1 ICU, 1 died) from Synthea into tests/fixtures/mini/synthea/.
Run once: uv run python scripts/make_mini_fixture.py
"""
from pathlib import Path

import duckdb

SRC = Path("data/synthea/100k_synthea_covid19_csv")
DST = Path("tests/fixtures/mini/synthea")
DST.mkdir(parents=True, exist_ok=True)
TABLES = ["patients", "conditions", "encounters", "procedures", "medications", "observations", "careplans"]

con = duckdb.connect()
for t in TABLES:
    con.execute(f"create view {t} as select * from read_csv_auto('{SRC/t}.csv', header=true)")

con.execute(
    """
create table pick as
with covid as (select distinct PATIENT from conditions where CODE = 840539006),
     inpat as (select distinct PATIENT from encounters where ENCOUNTERCLASS = 'inpatient'),
     icu   as (select distinct PATIENT from encounters where lower(DESCRIPTION) like '%intensive care%'),
     died  as (select Id as PATIENT from patients where DEATHDATE is not null),
     base  as (select c.PATIENT, (i.PATIENT is not null) as icu, (d.PATIENT is not null) as died
               from covid c join inpat p using (PATIENT)
               left join icu i using (PATIENT) left join died d using (PATIENT))
select PATIENT from (select PATIENT from base where icu and not died order by PATIENT limit 1)
union all select PATIENT from (select PATIENT from base where died order by PATIENT limit 1)
union all select PATIENT from (select PATIENT from base where not icu and not died order by PATIENT limit 3)
"""
)
ids = [r[0] for r in con.execute("select PATIENT from pick").fetchall()]
assert len(ids) == 5, ids
idlist = ",".join(f"'{i}'" for i in ids)
con.execute(f"copy (select * from patients where Id in ({idlist})) to '{DST/'patients.csv'}' (header, delimiter ',')")
for t in TABLES[1:]:
    con.execute(f"copy (select * from {t} where PATIENT in ({idlist})) to '{DST/t}.csv' (header, delimiter ',')")
print("wrote", ids)
