"""`auditpace cohort` — stage 1."""
from pathlib import Path

import typer

from auditpace.cohort.stage import CohortStage
from auditpace.protocol import load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store


def cohort(
    limit: int | None = typer.Option(None, help="Cap sample size (smoke runs)."),
    force: bool = typer.Option(False, help="Recompute even if tables exist."),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    s = load_settings()
    p = load_protocol(protocol)
    with Store(s.paths.processed_dir) as store:
        summary = CohortStage(s, p, store, limit_n=limit).run(force=force)
    if summary.n_quarantined:
        qfile = s.paths.processed_dir / "quarantine" / "cohort.jsonl"
        typer.echo(f"cohort: {summary.n_quarantined} item(s) quarantined; see {qfile}", err=True)
        raise typer.Exit(1)
