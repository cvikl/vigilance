"""`auditpace workbench` — stage 7: the clinician's review UI over S6's tables (no model calls)."""
from pathlib import Path

import typer
import uvicorn

from auditpace.estimate.compute import StaleTable
from auditpace.protocol import ProtocolNotLocked, load_protocol, require_locked
from auditpace.settings import load_settings
from auditpace.store import Store


def workbench(
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8080, help="Port."),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    s = load_settings()
    p = load_protocol(protocol)
    try:
        require_locked(p)
    except ProtocolNotLocked as e:
        typer.echo(f"workbench: {e}", err=True)
        raise typer.Exit(2) from e
    with Store(s.paths.processed_dir, read_only=True) as store:
        for table, prev in (("verdicts", "adjudicate"), ("cases", "cohort")):
            if not store.exists(table):
                typer.echo(f"workbench: missing {table}; run `auditpace {prev}` first", err=True)
                raise typer.Exit(2)
    from auditpace.workbench.app import create_app
    from auditpace.workbench.demo import read_held
    held = read_held()
    try:
        app = create_app(s.paths.processed_dir, p, held=held)
    except (StaleTable, ValueError, FileNotFoundError) as e:  # same exit-2 family as `estimate`
        typer.echo(f"workbench: {e}", err=True)
        raise typer.Exit(2) from e
    typer.echo(f"workbench: http://{host}:{port}/queue   demo: http://{host}:{port}/queue?demo=1"
               f"   held arrivals: {len(held)}", err=False)
    uvicorn.run(app, host=host, port=port, log_level="warning")
