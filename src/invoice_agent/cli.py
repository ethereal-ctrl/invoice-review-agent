"""Kommandozeile."""

import json
import os
from collections import Counter
from pathlib import Path
from typing import Annotated

import psycopg
import typer

from invoice_agent import db
from invoice_agent.config import lade
from invoice_agent.model import Welt

app = typer.Typer(no_args_is_help=True, help="Rechnungsprüfung: Generator, Eval-Ladder, Agent.")

ConfigOption = Annotated[Path, typer.Option("--config", "-c", exists=True, dir_okay=False)]
ZielOption = Annotated[Path, typer.Option("--out", "-o", file_okay=False)]
SpezOption = Annotated[Path, typer.Option("--spezifikation", exists=True, dir_okay=False)]

STANDARD_CONFIG = Path("configs/default.yaml")
STANDARD_ZIEL = Path("data/v1")
STANDARD_SPEZ = Path("docs/spezifikation.md")


@app.callback()
def main() -> None:
    """Rechnungsprüfung: Generator, Eval-Ladder, Agent."""


@app.command("config")
def config_zeigen(config: ConfigOption = STANDARD_CONFIG) -> None:
    """Geladene und validierte Konfiguration anzeigen."""
    typer.echo(lade(config).model_dump_json(indent=2))


@app.command("generate")
def generate(
    config: ConfigOption = STANDARD_CONFIG,
    out: ZielOption = STANDARD_ZIEL,
    spezifikation: SpezOption = STANDARD_SPEZ,
) -> None:
    """Welt, Rechnungen (PDF) und Gold-Labels erzeugen."""
    from invoice_agent.generator.ausgabe import schreibe
    from invoice_agent.generator.faelle import erzeuge

    settings = lade(config)
    ergebnis = erzeuge(settings)
    manifest = schreibe(ergebnis, settings, out, spezifikation)
    typen = Counter(f.gold.entscheidung.value for f in ergebnis.faelle)
    typer.echo(f"{manifest['anzahl']} Fälle nach {out} geschrieben: {dict(typen)}")
    typer.echo(f"Splits: {manifest['splits']}  Gold-SHA256: {manifest['gold_sha256']}")


@app.command("load")
def load(
    out: ZielOption = STANDARD_ZIEL,
    dsn: Annotated[str | None, typer.Option(envvar="IA_OWNER_DSN")] = None,
) -> None:
    """Erzeugte Welt und Fälle in Postgres laden (ersetzt erp und app)."""
    dsn = dsn or os.environ.get(
        "IA_OWNER_DSN", "postgresql://ia_owner:ia_owner_dev@localhost:55432/invoice"
    )
    welt = Welt.model_validate_json((out / "erp.json").read_text(encoding="utf-8"))
    with (out / "eval" / "gold.jsonl").open(encoding="utf-8") as f:
        fall_ids = [json.loads(zeile)["fall_id"] for zeile in f]
    with psycopg.connect(dsn) as conn:
        db.lade(conn, welt, fall_ids, (out / "eingang").resolve())
    typer.echo(f"{len(fall_ids)} Fälle und {len(welt.bestellungen)} Bestellungen geladen.")
