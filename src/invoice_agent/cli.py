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


def _lade_env(pfad: Path = Path(".env")) -> None:
    """KEY=WERT-Zeilen aus .env übernehmen; bereits gesetzte Variablen haben Vorrang."""
    if not pfad.exists():
        return
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, _, wert = zeile.partition("=")
        os.environ.setdefault(schluessel.strip(), wert.strip().strip('"').strip("'"))


@app.callback()
def main() -> None:
    """Rechnungsprüfung: Generator, Eval-Ladder, Agent."""
    _lade_env()


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


STANDARD_LAEUFE = Path("runs")
LaeufeOption = Annotated[Path, typer.Option("--runs", file_okay=False)]


def _prozent(x: float) -> str:
    return f"{x * 100:5.1f} %"


@app.command("eval")
def eval_lauf(
    stufe: Annotated[str, typer.Option("--stufe", "-s", help="b0, b1, regeln, llm:<profil>")],
    split: Annotated[str, typer.Option("--split", help="dev, smoke, test (Test nur einmal!)")],
    config: ConfigOption = STANDARD_CONFIG,
    daten: ZielOption = STANDARD_ZIEL,
    runs: LaeufeOption = STANDARD_LAEUFE,
    replay: Annotated[bool, typer.Option(help="Nur Antwort-Cache, keine API-Aufrufe")] = False,
) -> None:
    """Eine Stufe auf einem Split auswerten und den Lauf speichern."""
    from invoice_agent.eval.laeufe import SplitBereitsVerwendet
    from invoice_agent.eval.runner import lauf

    try:

        def fortschritt(i: int, n: int) -> None:
            if i % 10 == 0 or i == n:
                typer.echo(f"  {i}/{n}", err=True)

        modus = "replay" if replay else "live"
        ordner, m = lauf(stufe, split, lade(config), daten, runs, modus, fortschritt)
    except SplitBereitsVerwendet as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    typer.echo(f"Lauf: {ordner}")
    typer.echo(f"  Fälle                      {m.anzahl}")
    typer.echo(f"  Kosten pro 100 Rechnungen  {m.kosten_pro_100:>10} €")
    typer.echo(f"  ... bei 5 % Fehlerquote    {m.kosten_pro_100_real:>10} €")
    typer.echo(f"  Genauigkeit                {_prozent(m.genauigkeit)}")
    typer.echo(f"  Unsichere Aktionen         {m.unsichere_aktionen} ({_prozent(m.rate_unsicher)})")
    typer.echo(f"  Last für Menschen          {_prozent(m.last_mensch)}")
    typer.echo(f"  davon Kompetenzregel R15   {_prozent(m.interrupt_rate)}")
    typer.echo(f"  Extraktionsfehler          {m.extraktion_fehler}")
    erkennung = ", ".join(f"{t} {v:.0%}" for t, v in m.erkennung_pro_typ.items())
    fehlalarm = ", ".join(f"{t} {v:.0%}" for t, v in m.fehlalarm_pro_typ.items())
    typer.echo(f"  Erkennung                  {erkennung}")
    typer.echo(f"  Fehlalarm                  {fehlalarm}")
    typer.echo(f"  Latenz p50 / p95           {m.latenz_p50_ms:.0f} / {m.latenz_p95_ms:.0f} ms")
    if m.token_kosten_pro_100:
        typer.echo(f"  Token-Kosten pro 100       {m.token_kosten_pro_100} € (notionell)")
    if len(m.nach_layout) > 1:
        for layout, w in m.nach_layout.items():
            typer.echo(
                f"  Layout {layout} ({int(w['anzahl'])} Fälle)      Kosten/100 "
                f"{w['kosten_pro_100']:.2f} €, Genauigkeit {_prozent(w['genauigkeit'])}, "
                f"unsicher {_prozent(w['rate_unsicher'])}, "
                f"Extraktionsfehler {int(w['extraktion_fehler'])}"
            )


@app.command("compare")
def compare(
    lauf_a: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    lauf_b: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    config: ConfigOption = STANDARD_CONFIG,
    daten: ZielOption = STANDARD_ZIEL,
) -> None:
    """Lauf B gegen Lauf A mit gepaartem Bootstrap vergleichen (gleicher Split nötig)."""
    from invoice_agent.eval.bootstrap import vergleiche
    from invoice_agent.eval.laeufe import lade_meta, lade_vorhersagen
    from invoice_agent.eval.runner import auswahl
    from invoice_agent.gold import lade_gold

    meta_a, meta_b = lade_meta(lauf_a), lade_meta(lauf_b)
    if meta_a["split"] != meta_b["split"]:
        typer.echo("Die Läufe stammen aus verschiedenen Splits.", err=True)
        raise typer.Exit(2)
    gold = auswahl(lade_gold(daten / "eval" / "gold.jsonl"), str(meta_a["split"]))
    ergebnis = vergleiche(
        gold, lade_vorhersagen(lauf_a), lade_vorhersagen(lauf_b), lade(config).kosten
    )
    typer.echo(f"B = {meta_b['stufe']}  gegen  A = {meta_a['stufe']}  ({meta_a['split']})")
    for v in ergebnis:
        stern = " *" if v.signifikant else ""
        typer.echo(
            f"  {v.kennzahl:<16} A {v.a:10.3f}  B {v.b:10.3f}  "
            f"B-A {v.differenz:+10.3f}  95 % [{v.unten:+.3f}, {v.oben:+.3f}]{stern}"
        )
