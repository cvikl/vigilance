"""`auditpace read` — stage 4."""
from pathlib import Path

import typer

from auditpace.models import client_for, endpoint_serves
from auditpace.protocol import load_protocol
from auditpace.read.stage import ReadStage
from auditpace.settings import Settings, load_settings
from auditpace.store import Store


def _make_client(s: Settings):
    return client_for(s, "reader")


def read(
    limit: int | None = typer.Option(None, help="Cap number of batches (smoke runs)."),
    force: bool = typer.Option(False, help="Re-read ALL batches (stale partitions are removed first)."),
    workers: int | None = typer.Option(None, help="Concurrent batches (default from config read.workers)."),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    s = load_settings()
    p = load_protocol(protocol)
    if not s.mock and not endpoint_serves(s.models.reader):
        typer.echo(
            f"read: reader endpoint {s.models.reader.base_url} does not serve "
            f"{s.models.reader.model}; run `ONLY=4b make serve`", err=True,
        )
        raise typer.Exit(2)
    with Store(s.paths.processed_dir) as store:
        if not store.exists("pages"):
            typer.echo("read: missing pages; run `auditpace render` first", err=True)
            raise typer.Exit(2)
        try:
            stage = ReadStage(s, p, store, client=_make_client(s))
            summary = stage.run(limit=limit, force=force, workers=workers or s.read.workers)
        except (ValueError, FileNotFoundError) as e:
            typer.echo(f"read: {e}", err=True)
            raise typer.Exit(2) from e
    if summary.n_quarantined:
        qfile = s.paths.processed_dir / "quarantine" / "read.jsonl"
        typer.echo(f"read: {summary.n_quarantined} batch(es) quarantined; see {qfile}", err=True)
        raise typer.Exit(1)
