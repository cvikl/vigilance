"""AuditPace command-line entry point. Stages register themselves here."""
import typer

from auditpace import __version__

app = typer.Typer(help="AuditPace: verifiable, interpretable clinical audit pipeline.", no_args_is_help=True)

from auditpace.cmd_adjudicate import adjudicate
from auditpace.cmd_cohort import cohort
from auditpace.cmd_estimate import estimate
from auditpace.cmd_models import app as models_app
from auditpace.cmd_protocol import app as protocol_app
from auditpace.cmd_read import read
from auditpace.cmd_render import render
from auditpace.cmd_report import report
from auditpace.cmd_synth import synth
from auditpace.cmd_workbench import workbench

app.add_typer(protocol_app, name="protocol")
app.add_typer(models_app, name="models")
app.command()(cohort)
app.command()(synth)
app.command()(render)
app.command()(read)
app.command()(adjudicate)
app.command()(estimate)
app.command()(workbench)
app.command()(report)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"auditpace {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True, help="Show version."),
) -> None:
    """AuditPace CLI."""
