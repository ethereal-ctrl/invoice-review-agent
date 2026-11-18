"""Kommandozeile. Weitere Befehle (generate, eval, ladder) folgen mit den Bausteinen."""

from pathlib import Path
from typing import Annotated

import typer

from invoice_agent.config import lade

app = typer.Typer(no_args_is_help=True, help="Rechnungsprüfung: Generator, Eval-Ladder, Agent.")

ConfigOption = Annotated[Path, typer.Option("--config", "-c", exists=True, dir_okay=False)]


@app.callback()
def main() -> None:
    """Rechnungsprüfung: Generator, Eval-Ladder, Agent."""


@app.command("config")
def config_zeigen(config: ConfigOption = Path("configs/default.yaml")) -> None:
    """Geladene und validierte Konfiguration anzeigen."""
    typer.echo(lade(config).model_dump_json(indent=2))
