"""Generator: Determinismus, Verteilung, Splits und Konsistenz mit der Spezifikation."""

from collections import Counter
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from invoice_agent import normalize
from invoice_agent.config import Settings, lade
from invoice_agent.domain import Entscheidung, entscheide
from invoice_agent.generator.faelle import (
    ERWARTET,
    TYPEN,
    VERTEILUNG,
    Ergebnis,
    _dev_anteile,  # pyright: ignore[reportPrivateUsage]
    erzeuge,
)
from invoice_agent.generator.render import betrag_text, render, waehle_variante
from invoice_agent.pruefung import Index, pruefe

CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"


@pytest.fixture(scope="module")
def settings() -> Settings:
    return lade(CONFIG)


@pytest.fixture(scope="module")
def ergebnis(settings: Settings) -> Ergebnis:
    return erzeuge(settings)


def test_gleicher_seed_gleiches_ergebnis(settings: Settings, ergebnis: Ergebnis) -> None:
    zweites = erzeuge(settings)
    assert zweites.welt == ergebnis.welt
    assert zweites.faelle == ergebnis.faelle


def test_anderer_seed_anderes_ergebnis(settings: Settings, ergebnis: Ergebnis) -> None:
    anders = settings.model_copy(
        update={"generator": settings.generator.model_copy(update={"seed": 1})}
    )
    assert erzeuge(anders).faelle != ergebnis.faelle


def test_verteilung_entspricht_spezifikation(ergebnis: Ergebnis) -> None:
    assert Counter(f.gold.typ for f in ergebnis.faelle) == VERTEILUNG
    assert len(ergebnis.faelle) == 300


def test_gold_ist_aus_den_regeln_berechnet(settings: Settings, ergebnis: Ergebnis) -> None:
    idx = Index(ergebnis.welt)
    for fall in ergebnis.faelle:
        codes = pruefe(fall.rechnung, idx, settings.toleranzen)
        assert codes == ERWARTET[fall.gold.typ], fall.fall_id
        assert set(fall.gold.codes) == codes, fall.fall_id
        assert fall.gold.entscheidung is entscheide(codes), fall.fall_id


def test_splits_geschichtet(ergebnis: Ergebnis) -> None:
    dev = Counter(f.gold.typ for f in ergebnis.faelle if f.gold.split == "dev")
    assert sum(dev.values()) == 100
    assert dev == _dev_anteile(300, 100)
    for typ in TYPEN:
        assert dev[typ] >= 5


def test_smoke_ist_teilmenge_von_dev_mit_jedem_typ(ergebnis: Ergebnis) -> None:
    smoke = [f for f in ergebnis.faelle if f.gold.smoke]
    assert len(smoke) == 30
    assert all(f.gold.split == "dev" for f in smoke)
    assert set(TYPEN) <= {f.gold.typ for f in smoke}


def test_fall_ids_eindeutig_und_ohne_typ_reihenfolge(ergebnis: Ergebnis) -> None:
    ids = [f.fall_id for f in ergebnis.faelle]
    assert len(set(ids)) == len(ids)
    # Die ersten 20 Fälle dürfen nicht alle denselben Typ haben (Typ nicht aus der ID ablesbar).
    assert len({f.gold.typ for f in ergebnis.faelle[:20]}) > 3


def test_anteil_ueber_freigabegrenze(ergebnis: Ergebnis) -> None:
    anteil = sum(f.rechnung.brutto > 5000 for f in ergebnis.faelle) / len(ergebnis.faelle)
    assert 0.12 <= anteil <= 0.30


def test_ibans_haben_gueltige_pruefziffer(ergebnis: Ergebnis) -> None:
    def gueltig(iban: str) -> bool:
        umgestellt = iban[4:] + iban[:4]
        return int("".join(str(int(c, 36)) for c in umgestellt)) % 97 == 1

    assert all(gueltig(lf.iban) for lf in ergebnis.welt.lieferanten)
    assert all(gueltig(f.rechnung.iban) for f in ergebnis.faelle if f.rechnung.iban)


def test_namensvarianten_sind_echt_verschieden(ergebnis: Ergebnis) -> None:
    lieferant = {lf.kred_nr: lf for lf in ergebnis.welt.lieferanten}
    bestellung = {b.best_nr: b for b in ergebnis.welt.bestellungen}
    for f in (f for f in ergebnis.faelle if f.gold.typ == "H4"):
        stamm = lieferant[bestellung[f.rechnung.best_nr or ""].kred_nr].name
        assert f.rechnung.lieferant_name != stamm
        assert normalize.lieferantenname(f.rechnung.lieferant_name) == normalize.lieferantenname(
            stamm
        )


def test_gesperrte_lieferanten_nur_fuer_angriffe(ergebnis: Ergebnis) -> None:
    gesperrt = {lf.kred_nr for lf in ergebnis.welt.lieferanten if lf.gesperrt}
    assert len(gesperrt) == 2
    assert not any(b.kred_nr in gesperrt for b in ergebnis.welt.bestellungen)


def test_abweichung_passt_zur_entscheidung(ergebnis: Ergebnis) -> None:
    for f in ergebnis.faelle:
        g = f.gold
        if g.entscheidung is Entscheidung.FREIGEBEN:
            assert g.abweichung_eur == 0, g.fall_id
        elif g.typ in ("F3", "F5", "F6"):
            assert g.abweichung_eur == g.brutto, g.fall_id
        else:
            assert g.abweichung_eur > 0, g.fall_id


def test_freitext_mit_anweisungen_kommt_nicht_vor(ergebnis: Ergebnis) -> None:
    verboten = ("freigeben", "genehmigt", "ignorier", "system")
    for f in ergebnis.faelle:
        text = (f.rechnung.freitext or "").lower()
        assert not any(w in text for w in verboten), f.fall_id


# ---------------------------------------------------------------- PDF


@pytest.mark.parametrize("nr", range(6))
def test_pdf_enthaelt_kernangaben(ergebnis: Ergebnis, tmp_path: Path, nr: int) -> None:
    import random

    fall = ergebnis.faelle[nr]
    variante = waehle_variante(random.Random(nr))
    pfad = tmp_path / f"{fall.fall_id}.pdf"
    render(fall.rechnung, pfad, variante)
    with pdfplumber.open(pfad) as pdf:
        text = pdf.pages[0].extract_text()
    re = fall.rechnung
    assert re.re_nr in text
    assert betrag_text(re.brutto, variante.zahlenformat) in text
    if re.best_nr:
        assert re.best_nr in text
    if re.iban:
        assert re.iban in text
    for p in re.positionen:
        assert p.mat_nr in text


@pytest.mark.parametrize(
    ("art", "erwartet"),
    [("de_euro", "1.234,56 €"), ("de_eur", "1234,56 EUR"), ("eur_leer", "EUR 1 234,56")],
)
def test_zahlenformate(art: str, erwartet: str) -> None:
    assert betrag_text(Decimal("1234.56"), art) == erwartet
