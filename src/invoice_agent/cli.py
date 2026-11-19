"""Kommandozeile."""

import json
import os
from collections import Counter
from decimal import Decimal
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
STANDARD_ANGRIFFE = Path("data/v1/angriffe")


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


def _pruefe_gate(pfad: Path, stufe: str, split: str, unsicher: int, kosten: Decimal) -> str | None:
    """None, wenn das Gate hält; sonst der Grund."""
    import yaml

    roh = yaml.safe_load(pfad.read_text(encoding="utf-8"))
    referenz = roh.get(split, {}).get(stufe)
    if referenz is None:
        return f"kein eingefrorener Wert für {stufe} auf {split}"
    if unsicher > 0:
        return f"{unsicher} unsichere Aktionen"
    grenze = Decimal(str(referenz)) * (1 + Decimal(str(roh["toleranz_prozent"])) / 100)
    if kosten > grenze:
        return f"Kosten {kosten} € pro 100 > {grenze:.2f} € (eingefroren {referenz} €)"
    return None


@app.command("eval")
def eval_lauf(
    stufe: Annotated[str, typer.Option("--stufe", "-s", help="b0, b1, regeln, llm:<profil>")],
    split: Annotated[str, typer.Option("--split", help="dev, smoke, test (Test nur einmal!)")],
    config: ConfigOption = STANDARD_CONFIG,
    daten: ZielOption = STANDARD_ZIEL,
    runs: LaeufeOption = STANDARD_LAEUFE,
    replay: Annotated[bool, typer.Option(help="Nur Antwort-Cache, keine API-Aufrufe")] = False,
    max_unsicher: Annotated[
        int | None, typer.Option(help="Gate: Exit-Code 1 bei mehr unsicheren Aktionen")
    ] = None,
    gate: Annotated[
        Path | None,
        typer.Option(exists=True, dir_okay=False, help="Regression Gate (configs/gate.yaml)"),
    ] = None,
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
    if max_unsicher is not None and m.unsichere_aktionen > max_unsicher:
        typer.echo(f"Gate verletzt: {m.unsichere_aktionen} unsichere Aktionen", err=True)
        raise typer.Exit(1)
    if gate is not None:
        verletzt = _pruefe_gate(gate, stufe, split, m.unsichere_aktionen, m.kosten_pro_100)
        if verletzt:
            typer.echo(f"Gate verletzt: {verletzt}", err=True)
            raise typer.Exit(1)
        typer.echo("  Gate                       bestanden")


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


@app.command("angriffe-erzeugen")
def angriffe_erzeugen(
    config: ConfigOption = STANDARD_CONFIG,
    out: ZielOption = STANDARD_ANGRIFFE,
) -> None:
    """Angriffsset A1-A12 auf einer Kopie der Hauptwelt erzeugen (Hauptdaten bleiben gleich)."""
    from invoice_agent.generator.angriffe import erzeuge_angriffe, schreibe_angriffe
    from invoice_agent.generator.faelle import erzeuge

    settings = lade(config)
    a = erzeuge_angriffe(settings, erzeuge(settings))
    manifest = schreibe_angriffe(a, settings, out)
    typer.echo(f"{manifest['anzahl']} Angriffe nach {out} geschrieben.")


@app.command("angriffe")
def angriffe_lauf(
    stufe: Annotated[str, typer.Option("--stufe", "-s", help="b0, regeln, llm:<p>, agent:<p>")],
    config: ConfigOption = STANDARD_CONFIG,
    daten: ZielOption = STANDARD_ANGRIFFE,
    runs: LaeufeOption = STANDARD_LAEUFE,
    replay: Annotated[bool, typer.Option(help="Nur Antwort-Cache, keine API-Aufrufe")] = False,
) -> None:
    """Alle Angriffe gegen eine Stufe laufen lassen. Exit-Code 1, wenn einer durchkommt."""
    from invoice_agent.eval.angriffe import bewerte
    from invoice_agent.eval.laeufe import lade_vorhersagen
    from invoice_agent.eval.runner import lauf
    from invoice_agent.generator.angriffe import lade_angriffe

    modus = "replay" if replay else "live"
    ordner, _ = lauf(stufe, "angriffe", lade(config), daten, runs, modus)
    befunde = bewerte(lade_angriffe(daten / "eval" / "angriffe.jsonl"), lade_vorhersagen(ordner))
    typer.echo(f"Lauf: {ordner}")
    for b in befunde:
        zeichen = "ok  " if b.bestanden else "FREI"
        typer.echo(
            f"  {zeichen} {b.angriff.nr:<4} {b.angriff.titel:<52} "
            f"{b.vorhersage.effektiv.value:<14} {b.schicht}"
        )
    durch = sum(not b.bestanden for b in befunde)
    typer.echo(f"Automatische Freigaben: {durch} von {len(befunde)}")
    if durch:
        raise typer.Exit(1)


AgentDsn = Annotated[str | None, typer.Option("--dsn", envvar="IA_AGENT_DSN")]
STANDARD_AGENT_DSN = "postgresql://ia_agent:ia_agent_dev@localhost:55432/invoice"


@app.command("worker")
def worker(
    stufe: Annotated[str, typer.Option("--stufe", "-s", help="regeln, llm:<p>, agent:<p>")],
    threads: Annotated[int, typer.Option(min=1)] = 4,
    maximal: Annotated[int | None, typer.Option(help="Höchstens so viele Fälle")] = None,
    haengend_min: Annotated[int, typer.Option(help="In Arbeit länger als N Minuten = neu")] = 30,
    config: ConfigOption = STANDARD_CONFIG,
    dsn: AgentDsn = None,
) -> None:
    """Fälle aus der Postgres-Queue abarbeiten (als Rolle ia_agent, Audit in Postgres)."""
    from datetime import UTC, datetime

    from invoice_agent import queue
    from invoice_agent.audit import PostgresAudit
    from invoice_agent.erp import PostgresErp
    from invoice_agent.eval.metriken import Vorhersage
    from invoice_agent.eval.runner import baue_stufe

    dsn = dsn or STANDARD_AGENT_DSN
    settings = lade(config)
    run_id = f"worker_{stufe}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    with psycopg.connect(dsn) as conn:
        frei = queue.gib_haengende_frei(conn, haengend_min)
        welt = queue.lies_welt(conn)
    if frei:
        typer.echo(f"{frei} hängende Fälle wieder geöffnet.")
    audit, erp = PostgresAudit(dsn), PostgresErp(dsn)
    pool = None
    try:
        checkpointer = None
        if stufe.startswith("agent:"):  # Fortsetzen nach interrupt aus dem Cockpit
            from invoice_agent.checkpoint import postgres_checkpointer

            checkpointer, pool = postgres_checkpointer(dsn, anlegen=True)
        st = baue_stufe(stufe, settings, welt, "live", audit, run_id, erp, checkpointer)

        def melde(v: Vorhersage) -> None:
            typer.echo(f"  {v.fall_id}  {v.effektiv.value:<14} {v.policy_regel or ''}")

        bilanz = queue.arbeite(dsn, st, run_id, threads, maximal, melde)
    finally:
        audit.schliesse()
        erp.schliesse()
        if pool is not None:
            pool.close()
    typer.echo(f"Lauf {run_id}: {len(bilanz.erledigt)} erledigt, {len(bilanz.fehler)} Fehler")


@app.command("ui")
def ui(
    port: Annotated[int, typer.Option()] = 8000,
    config: ConfigOption = STANDARD_CONFIG,
    daten: ZielOption = STANDARD_ZIEL,
    runs: LaeufeOption = STANDARD_LAEUFE,
    dsn: Annotated[str | None, typer.Option("--dsn", envvar="IA_MENSCH_DSN")] = None,
) -> None:
    """Freigabe-Cockpit starten (Rolle ia_mensch, nur lokal: http://127.0.0.1:<port>)."""
    import uvicorn

    from invoice_agent.ui.app import erstelle_app

    dsn = dsn or "postgresql://ia_mensch:ia_mensch_dev@localhost:55432/invoice"
    app_ = erstelle_app(dsn, lade(config), daten.resolve(), runs.resolve())
    uvicorn.run(app_, host="127.0.0.1", port=port, log_level="warning")
