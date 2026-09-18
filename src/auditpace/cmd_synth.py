"""`auditpace synth` — stage 2."""
from pathlib import Path

import typer

from auditpace.protocol import load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store
from auditpace.synth.stage import SynthStage


def synth(
    limit: int | None = typer.Option(None, help="Cap number of batches (smoke runs)."),
    force: bool = typer.Option(False, help="Re-author batches that already have a partition."),
    workers: int | None = typer.Option(None, help="Concurrent claude -p calls (default from config synth.workers)."),
    batch_size: int | None = typer.Option(None, help="Patients per call (default from config synth.batch_size)."),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    s = load_settings()
    p = load_protocol(protocol)
    with Store(s.paths.processed_dir) as store:
        missing = [t for t in ("patients", "events", "cases") if not store.exists(t)]
        if missing:
            typer.echo(f"synth: missing {missing}; run `auditpace cohort` first", err=True)
            raise typer.Exit(2)
        stage = SynthStage(s, p, store, batch_size=batch_size)
        try:
            summary = stage.run(limit=limit, force=force, workers=workers or s.synth.workers)
        except ValueError as e:
            typer.echo(f"synth: {e}", err=True)
            raise typer.Exit(2) from e
    if summary.n_quarantined:
        qfile = s.paths.processed_dir / "quarantine" / "synth.jsonl"
        typer.echo(f"synth: {summary.n_quarantined} batch(es) quarantined; see {qfile}", err=True)
        raise typer.Exit(1)
