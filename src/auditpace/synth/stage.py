"""Stage 2: synth → documents (S2 design §9). One item = one batch of patients = one claude -p call."""
import json
from dataclasses import dataclass

import pandas as pd

from auditpace.models import ClaudeCLI, ModelJSONError
from auditpace.stage import Stage
from auditpace.synth.facts import check_bank
from auditpace.synth.plan import DocSpec, build_plan
from auditpace.synth.prompt import OUTPUT_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from auditpace.synth.validate import validate_batch

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Batch:
    batch_id: str
    patient_ids: tuple[str, ...]


class SynthStage(Stage):
    name = "synth"

    def __init__(self, settings, protocol, store, client=None, batch_size: int | None = None):
        super().__init__(settings, protocol, store)
        check_bank(protocol.criteria)
        self.client = client or ClaudeCLI(settings.synth.model, settings.mock, settings.paths.fixtures_dir,
                                          timeout_s=settings.synth.timeout_s)
        self.model = settings.synth.model
        self.batch_size = batch_size or settings.synth.batch_size
        self.seed = protocol.cohort.sample.seed
        self._patients: pd.DataFrame | None = None
        self._events: pd.DataFrame | None = None
        self._cases: pd.DataFrame | None = None

    def _load(self) -> None:
        if self._patients is None:
            self._patients = self.store.read("patients").set_index("patient_id", drop=False).sort_index()
            self._events = self.store.read("events")
            self._cases = self.store.read("cases")

    def items(self):
        self._load()
        ids = list(self._patients.index)
        for n, i in enumerate(range(0, len(ids), self.batch_size)):
            yield Batch(f"b{n:04d}", tuple(ids[i:i + self.batch_size]))

    def _plans(self, batch: Batch) -> list[tuple[pd.Series, list[DocSpec]]]:
        self._load()
        order = list(self.protocol.events)
        out = []
        for pid in batch.patient_ids:
            pat = self._patients.loc[pid]
            ev = self._events[self._events.patient_id == pid]
            ca = self._cases[self._cases.patient_id == pid]
            out.append((pat, build_plan(pat, ev, ca, self.protocol.criteria, order, self.seed)))
        return out

    def _partition(self, batch: Batch):
        return self.store.part_dir("documents") / f"{batch.batch_id}.parquet"

    def is_done(self, batch: Batch) -> bool:
        part = self._partition(batch)
        if not part.exists():
            return False
        have = set(pd.read_parquet(part, columns=["doc_id"]).doc_id)
        want = {s.doc_id for _, specs in self._plans(batch) for s in specs}
        return want == have

    def _planned_ids(self) -> dict[str, set[str]]:
        return {b.batch_id: {s.doc_id for _, specs in self._plans(b) for s in specs} for b in self.items()}

    def run(self, limit: int | None = None, force: bool = False, workers: int = 1):
        """Guard against a `--batch-size` change: a partition whose on-disk doc_ids no longer
        match what the current batch_size would produce (renumbered batches, split/merged
        patients) would otherwise sit alongside freshly-written partitions and duplicate doc_ids
        on read. Refuse unless `force` is given, in which case the stale files are deleted first.
        """
        part_dir = self.store.part_dir("documents")
        existing = {}
        if part_dir.exists():
            for p in part_dir.glob("*.parquet"):
                existing[p.stem] = set(pd.read_parquet(p, columns=["doc_id"]).doc_id)
        planned = self._planned_ids()
        orphans = {stem for stem, have in existing.items() if have != planned.get(stem, set())}
        if orphans:
            if force:
                for stem in orphans:
                    (part_dir / f"{stem}.parquet").unlink()
            else:
                raise ValueError(
                    f"documents/ has partitions {sorted(orphans)} not produced by batch_size={self.batch_size}; "
                    "rerun with the original --batch-size or with --force"
                )
        return super().run(limit=limit, force=force, workers=workers)

    def process(self, batch: Batch) -> int:
        plans = self._plans(batch)
        prompt, planned = build_user_prompt(plans)
        user = prompt
        errors: list[str] = []
        for _ in range(MAX_ATTEMPTS):
            try:
                returned = self.client.chat_json(SYSTEM_PROMPT, user, OUTPUT_SCHEMA)
            except ModelJSONError as e:
                errors = [f"model call failed: {e}"]
                user = prompt  # transport failure, not a content rejection: retry the same prompt
                continue
            errors = validate_batch(planned, returned)
            if not errors:
                break
            user = prompt + "\n\nPrevious attempt rejected:\n- " + "\n- ".join(errors)
        else:
            raise ValueError(f"{batch.batch_id}: rejected after {MAX_ATTEMPTS} attempts: {errors}")
        texts = {d["doc_id"]: d["text"] for d in returned["documents"]}
        rows = []
        for aid, s in planned.items():
            rows.append({
                "doc_id": s.doc_id, "patient_id": s.patient_id, "doc_type": s.doc_type,
                "authored_ts": s.authored_ts, "style": s.style, "text": texts[aid],
                "planted_facts": json.dumps([f.to_dict() for f in s.facts]),
                "batch_id": batch.batch_id, "model": self.model, "prompt_version": PROMPT_VERSION,
            })
        df = pd.DataFrame(rows)
        df["authored_ts"] = pd.to_datetime(df.authored_ts).astype("datetime64[us]")
        self.store.write_part("documents", batch.batch_id, df, self.protocol.hash)
        print(f"synth: {batch.batch_id} ok, {len(df)} documents", flush=True)
        return len(df)
