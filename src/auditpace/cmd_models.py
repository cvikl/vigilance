"""`auditpace models check` — verify configured model endpoints are up."""
import httpx
import typer

from auditpace.settings import load_settings

app = typer.Typer(help="Model endpoint utilities.")


@app.command()
def check() -> None:
    s = load_settings()
    if s.mock:
        typer.echo("mock mode: skipping endpoint checks")
        raise typer.Exit(0)
    failed = False
    for role in ("adjudicator", "reader", "designer", "reporter"):
        ep = getattr(s.models, role)
        if ep is None:
            typer.echo(f"{role}: (not configured)")
            continue
        try:
            r = httpx.get(f"{ep.base_url}/models", timeout=5)
            r.raise_for_status()
            ids = [m["id"] for m in r.json().get("data", [])]
            ok = ep.model in ids
            typer.echo(f"{role}: {ep.model} @ {ep.base_url} → {'ok' if ok else 'FAIL (served: ' + ','.join(ids) + ')'}")
            failed |= not ok
        except (httpx.HTTPError, ValueError, KeyError) as e:
            typer.echo(f"{role}: {ep.model} @ {ep.base_url} → FAIL ({type(e).__name__})")
            failed = True
    raise typer.Exit(1 if failed else 0)
