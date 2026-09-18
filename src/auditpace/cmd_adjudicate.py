"""`auditpace adjudicate` — stage 5."""
from pathlib import Path

import typer

from auditpace.adjudicate.stage import AdjudicateStage
from auditpace.models import client_for, endpoint_serves
from auditpace.protocol import load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store


def adjudicate(
    limit: int | None = typer.Option(None, help="Cap number of batches (smoke runs)."),
    force: bool = typer.Option(False, help="Re-adjudicate ALL batches (stale partitions are removed first)."),
    workers: int | None = typer.Option(None, help="Concurrent batches (default from config adjudicate.workers)."),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    s = load_settings()
    p = load_protocol(protocol)
    ep = s.models.adjudicator
    if ep is None:
        typer.echo("adjudicate: no adjudicator endpoint in config.yaml", err=True)
        raise typer.Exit(2)
    if not s.mock and not endpoint_serves(ep):
        typer.echo(f"adjudicate: adjudicator endpoint {ep.base_url} does not serve {ep.model}; "
                   "run `ONLY=27b make serve`", err=True)
        raise typer.Exit(2)
    with Store(s.paths.processed_dir) as store:
        for table, prev in (("cases", "cohort"), ("documents", "synth"), ("readings", "read")):
            if not store.exists(table):
                typer.echo(f"adjudicate: missing {table}; run `auditpace {prev}` first", err=True)
                raise typer.Exit(2)
        try:
            stage = AdjudicateStage(s, p, store, client=client_for(s, "adjudicator"))
            summary = stage.run(limit=limit, force=force, workers=workers or s.adjudicate.workers)
        except (ValueError, FileNotFoundError) as e:
            typer.echo(f"adjudicate: {e}", err=True)
            raise typer.Exit(2) from e
    if summary.n_quarantined:
        qfile = s.paths.processed_dir / "quarantine" / "adjudicate.jsonl"
        typer.echo(f"adjudicate: {summary.n_quarantined} batch(es) quarantined; see {qfile}", err=True)
        raise typer.Exit(1)
