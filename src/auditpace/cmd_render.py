"""`auditpace render` — stage 3."""
from pathlib import Path

import typer

from auditpace.protocol import load_protocol
from auditpace.render.stage import RenderStage
from auditpace.settings import load_settings
from auditpace.store import Store


def render(
    limit: int | None = typer.Option(None, help="Cap number of batches (smoke runs)."),
    force: bool = typer.Option(
        False,
        help=(
            "Re-render ALL batches (also required after `auditpace synth --force`; "
            "stale partitions are removed first)."
        ),
    ),
    workers: int | None = typer.Option(
        None, help="Concurrent browsers (default from config render.workers)."
    ),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    s = load_settings()
    p = load_protocol(protocol)
    with Store(s.paths.processed_dir) as store:
        if not store.exists("documents"):
            typer.echo("render: missing documents; run `auditpace synth` first", err=True)
            raise typer.Exit(2)
        stage = RenderStage(s, p, store)
        try:
            summary = stage.run(limit=limit, force=force, workers=workers or s.render.workers)
        except ValueError as e:
            typer.echo(f"render: {e}", err=True)
            raise typer.Exit(2) from e
    if summary.n_quarantined:
        qfile = s.paths.processed_dir / "quarantine" / "render.jsonl"
        typer.echo(f"render: {summary.n_quarantined} batch(es) quarantined; see {qfile}", err=True)
        raise typer.Exit(1)
