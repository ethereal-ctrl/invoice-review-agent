"""Stufen: Regex-Extraktion, Stufe 1, Baselines und Trennung von Generator und Gold."""

import ast
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_agent.config import Settings, lade
from invoice_agent.domain import Entscheidung
from invoice_agent.generator.faelle import Ergebnis, erzeuge
from invoice_agent.generator.render import render, waehle_variante
from invoice_agent.stufen.regeln import regeln
from invoice_agent.stufen.regex_extraktion import (
    ExtraktionsFehler,
    aus_pdf,
    aus_text,
    betrag,
    datum,
)

WURZEL = Path(__file__).parents[1]
CONFIG = WURZEL / "configs" / "default.yaml"


@pytest.fixture(scope="module")
def settings() -> Settings:
    return lade(CONFIG)


@pytest.fixture(scope="module")
def ergebnis(settings: Settings) -> Ergebnis:
    return erzeuge(settings)


@pytest.mark.parametrize(
    ("text", "erwartet"),
    [("1.234,56 €", "1234.56"), ("1234,56 EUR", "1234.56"), ("EUR 1 234,56", "1234.56"),
     ("12,80 €", "12.80"), ("-3,50 €", "-3.50")],
)  # fmt: skip
def test_betrag(text: str, erwartet: str) -> None:
    assert betrag(text) == Decimal(erwartet)


@pytest.mark.parametrize("text", ["23.09.2026", "2026-09-23", "23. Sep. 2026"])
def test_datum(text: str) -> None:
    assert datum(text) == date(2026, 9, 23)


def test_unlesbares_dokument_wirft() -> None:
    with pytest.raises(ExtraktionsFehler):
        aus_text("Kein Rechnungsformat\nnur Text")


@pytest.mark.parametrize("nr", range(12))
def test_extraktion_entspricht_der_wahren_rechnung(
    ergebnis: Ergebnis, tmp_path: Path, nr: int
) -> None:
    fall = ergebnis.faelle[nr * 7]
    pfad = tmp_path / "re.pdf"
    render(fall.rechnung, pfad, waehle_variante(random.Random(nr)))
    gelesen = aus_pdf(pfad)
    erwartet = fall.rechnung.model_copy(
        update={
            "freitext": None,
            "positionen": tuple(
                p.model_copy(update={"bezeichnung": p.bezeichnung[:36]})
                for p in fall.rechnung.positionen
            ),
        }
    )
    assert gelesen == erwartet


def test_stufe1_eskaliert_bei_extraktionsfehler(
    settings: Settings, ergebnis: Ergebnis, tmp_path: Path
) -> None:
    kaputt = tmp_path / "kaputt.pdf"
    from reportlab.pdfgen.canvas import Canvas

    c = Canvas(str(kaputt))
    c.drawString(50, 800, "Kein Rechnungsformat")
    c.save()
    v = regeln(settings, ergebnis.welt).entscheide("X", kaputt)
    assert v.entscheidung is Entscheidung.ESKALIEREN
    assert not v.extraktion_ok


def test_stufen_importieren_weder_generator_noch_gold() -> None:
    verboten = ("invoice_agent.generator", "invoice_agent.gold")
    for datei in (WURZEL / "src" / "invoice_agent" / "stufen").glob("*.py"):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.ImportFrom) and knoten.module:
                assert not knoten.module.startswith(verboten), f"{datei.name}: {knoten.module}"
            if isinstance(knoten, ast.Import):
                for alias in knoten.names:
                    assert not alias.name.startswith(verboten), f"{datei.name}: {alias.name}"


def test_stufe1_gibt_unbekanntes_layout_nie_frei(
    settings: Settings, ergebnis: Ergebnis, tmp_path: Path
) -> None:
    stufe = regeln(settings, ergebnis.welt)
    for nr, fall in enumerate(ergebnis.faelle[:10]):
        pfad = tmp_path / f"{nr}.pdf"
        render(fall.rechnung, pfad, waehle_variante(random.Random(nr), "C"))
        v = stufe.entscheide(fall.fall_id, pfad)
        assert v.effektiv is not Entscheidung.FREIGEBEN or v.extraktion_ok
