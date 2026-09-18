"""`auditpace report` — stage 8: the audit report from S6's aggregates through the gateway."""
from pathlib import Path

import typer

from auditpace.estimate.compute import StaleTable, _check_hash
from auditpace.protocol import ProtocolNotLocked, load_protocol, require_locked
from auditpace.report.gateway import GatewayViolation
from auditpace.report.stage import ReportStage
from auditpace.settings import load_settings
from auditpace.store import Store

REQUIRED = (("estimates", "estimate"), ("alerts", "estimate"), ("timelost", "estimate"), ("funnel", "estimate"),
            ("runchart", "estimate"), ("verdicts", "adjudicate"), ("patients", "cohort"), ("cohort_completeness", "cohort"))


def report(
    model: str = typer.Option("medgemma", help="Report writer: medgemma (reporter role) or claude (claude -p)."),
    no_model: bool = typer.Option(False, "--no-model", help="Skip the report writer; every narrative paragraph is withheld."),
    compare_to: str | None = typer.Option(None, help="Run id to compare against (default: newest prior run, same protocol)."),
    out: Path = typer.Option(Path("docs/report.md"), help="Where the report is copied (the workbench Report tab reads it)."),
    protocol: Path = typer.Option(Path("protocol.yaml"), help="Locked protocol file."),
) -> None:
    if model not in ("medgemma", "claude"):
        typer.echo(f"report: --model must be medgemma or claude, not {model!r}", err=True)
        raise typer.Exit(2)
    s = load_settings()
    p = load_protocol(protocol)
    try:
        require_locked(p)
    except ProtocolNotLocked as e:
        typer.echo(f"report: {e}", err=True)
        raise typer.Exit(2) from e
    with Store(s.paths.processed_dir) as store:
        for table, prev in REQUIRED:
            if not store.exists(table):
                typer.echo(f"report: missing {table}; run `auditpace {prev}` first", err=True)
                raise typer.Exit(2)
        try:
            for table, _ in REQUIRED:
                # verdicts is read in full elsewhere in the pipeline; here only the hash column is
                # needed, so `store.read(table)[["protocol_hash"]]` avoids re-reading the evidence
                # blobs twice in one CLI invocation.
                if table == "verdicts":
                    _check_hash(store.read(table)[["protocol_hash"]], table, p)
                else:
                    _check_hash(store.read(table), table, p)
            for table in ("cases", "coverage"):
                if store.exists(table):
                    _check_hash(store.read(table), table, p)
            ReportStage(s, p, store, model=None if no_model else model, compare_to=compare_to, out=out).run()
        except (StaleTable, GatewayViolation, ValueError, FileNotFoundError) as e:
            typer.echo(f"report: {e}", err=True)
            raise typer.Exit(2) from e
