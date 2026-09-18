"""`auditpace protocol ...` subcommands."""
from pathlib import Path

import typer

from auditpace.protocol import canonical_hash, load_protocol, lock_protocol

app = typer.Typer(help="Validate and lock the audit protocol.")


@app.command()
def validate(path: Path = typer.Argument(Path("protocol.yaml"))) -> None:
    p = load_protocol(path)
    typer.echo(f"ok: {p.protocol_id} ({len(p.criteria)} criteria) hash={canonical_hash(p)[:12]} locked={p.locked}")


@app.command()
def lock(path: Path = typer.Argument(Path("protocol.yaml"))) -> None:
    h = lock_protocol(path)
    typer.echo(f"locked {path} hash={h}")
