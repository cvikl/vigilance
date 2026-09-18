"""`auditpace estimate` — stage 6."""
from pathlib import Path

import typer

from auditpace.estimate.compute import StaleTable
from auditpace.estimate.stage import EstimateStage
from auditpace.protocol import ProtocolNotLocked, load_protocol
from auditpace.settings import load_settings
from auditpace.store import Store


def estimate(
    coverage: bool = typer.Option(False, help="Also run the coverage experiment (reads cases.breached; evaluation only)."),
    sims: int = typer.Option(500, help="Simulations per fraction for --coverage."),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    s = load_settings()
    p = load_protocol(protocol)
    with Store(s.paths.processed_dir) as store:
        for table, prev in (("verdicts", "adjudicate"), ("cases", "cohort")):
            if not store.exists(table):
                typer.echo(f"estimate: missing {table}; run `auditpace {prev}` first", err=True)
                raise typer.Exit(2)
        try:
            EstimateStage(s, p, store, coverage=coverage, sims=sims).run()
        except (ProtocolNotLocked, StaleTable, ValueError, FileNotFoundError) as e:  # spec §11: all exit 2
            typer.echo(f"estimate: {e}", err=True)
            raise typer.Exit(2) from e
