"""Regelwerk R1-R13 und R15 gegen eine kleine, von Hand gebaute Welt."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from invoice_agent.config import PolicyConfig, Toleranzen
from invoice_agent.domain import Code
from invoice_agent.model import (
    Bestellung,
    BestPos,
    Lieferant,
    Material,
    Rechnung,
    ReHist,
    ReHistPos,
    RePos,
    UstZeile,
    Welt,
    WePos,
)
from invoice_agent.pruefung import Index, kumuliert_brutto, pruefe

TOL = Toleranzen(preis_prozent=D("2.0"), betrag_eur=D("0.01"), duplikat_tage=30)
POLICY = PolicyConfig(freigabegrenze_eur=D("5000.00"), fenster_tage=30)

MUELLER = Lieferant(
    kred_nr="K1",
    name="Müller GmbH",
    strasse="Hauptstr. 1",
    ort="12345 Berlin",
    ust_id="DE111111111",
    iban="DE89370400440532013000",
)
SCHMIDT = Lieferant(
    kred_nr="K2",
    name="Schmidt AG",
    strasse="Ring 2",
    ort="54321 Köln",
    ust_id="DE222222222",
    iban="DE02120300000000202051",
)
GESPERRT = Lieferant(
    kred_nr="K3",
    name="Alt KG",
    strasse="Weg 3",
    ort="11111 Ort",
    ust_id="DE333333333",
    iban="DE44500105175407324931",
    gesperrt=True,
)
SCHRAUBE = Material(mat_nr="M1", bezeichnung="Schraube", ust_satz=D("19"), einheiten={"KAR": 12})
BUCH = Material(mat_nr="M2", bezeichnung="Buch", ust_satz=D("7"))

BESTELLUNG = Bestellung(
    best_nr="B1",
    kred_nr="K1",
    datum=date(2026, 10, 1),
    positionen=(
        BestPos(pos=1, mat_nr="M1", menge=120, preis_netto=D("1.00")),
        BestPos(pos=2, mat_nr="M2", menge=10, preis_netto=D("20.00")),
    ),
)
BESTELLUNG_GESPERRT = Bestellung(
    best_nr="B3",
    kred_nr="K3",
    datum=date(2026, 10, 1),
    positionen=(BestPos(pos=1, mat_nr="M2", menge=10, preis_netto=D("20.00")),),
)


def _welt(re_hist: tuple[ReHist, ...] = (), geliefert: tuple[int, int] = (120, 10)) -> Welt:
    return Welt(
        lieferanten=(MUELLER, SCHMIDT, GESPERRT),
        materialien=(SCHRAUBE, BUCH),
        bestellungen=(BESTELLUNG, BESTELLUNG_GESPERRT),
        wareneingaenge=(
            WePos(
                we_nr="W1",
                best_nr="B1",
                pos=1,
                menge_geliefert=geliefert[0],
                datum=date(2026, 10, 5),
            ),
            WePos(
                we_nr="W1",
                best_nr="B1",
                pos=2,
                menge_geliefert=geliefert[1],
                datum=date(2026, 10, 5),
            ),
            WePos(we_nr="W3", best_nr="B3", pos=1, menge_geliefert=10, datum=date(2026, 10, 5)),
        ),
        re_hist=re_hist,
    )


def _rechnung(**aenderungen: object) -> Rechnung:
    """Korrekte Rechnung über die volle Bestellung B1: 120 ST à 1,00 + 10 Bücher à 20,00."""
    basis = Rechnung(
        re_nr="RE-1043",
        datum=date(2026, 10, 8),
        lieferant_name="Müller GmbH",
        lieferant_strasse="Hauptstr. 1",
        lieferant_ort="12345 Berlin",
        ust_id="DE111111111",
        best_nr="B1",
        iban="DE89370400440532013000",
        positionen=(
            RePos(
                mat_nr="M1",
                bezeichnung="Schraube",
                menge=120,
                einheit="ST",
                preis_netto=D("1.00"),
                betrag_netto=D("120.00"),
                ust_satz=D("19"),
            ),
            RePos(
                mat_nr="M2",
                bezeichnung="Buch",
                menge=10,
                einheit="ST",
                preis_netto=D("20.00"),
                betrag_netto=D("200.00"),
                ust_satz=D("7"),
            ),
        ),
        netto=D("320.00"),
        ust=(
            UstZeile(satz=D("19"), netto=D("120.00"), betrag=D("22.80")),
            UstZeile(satz=D("7"), netto=D("200.00"), betrag=D("14.00")),
        ),
        brutto=D("356.80"),
    )
    return basis.model_copy(update=aenderungen)


def _pruefe(re: Rechnung, welt: Welt | None = None) -> frozenset[Code]:
    return pruefe(re, Index(welt or _welt()), TOL)


def test_korrekte_rechnung_hat_keine_codes() -> None:
    assert _pruefe(_rechnung()) == frozenset()


# ------------------------------------------------------------ R1, R2, R3, R4


def test_r1_unbekannte_bestellung() -> None:
    assert Code.P2 in _pruefe(_rechnung(best_nr="B999"))


def test_r1_fehlende_bestellung() -> None:
    assert Code.P2 in _pruefe(_rechnung(best_nr=None))


@pytest.mark.parametrize("ust_id", [None, "DE999999999", "DE222222222"])
def test_r2_ust_id_fehlt_unbekannt_oder_fremd(ust_id: str | None) -> None:
    assert _pruefe(_rechnung(ust_id=ust_id)) == {Code.F6}


def test_r2_ust_id_mit_leerzeichen_ist_gleich() -> None:
    assert _pruefe(_rechnung(ust_id="de 111 111 111")) == frozenset()


def test_r3_namensvariante_ist_kein_mangel() -> None:
    assert _pruefe(_rechnung(lieferant_name="MUELLER GmbH & Co. KG")) == frozenset()


def test_r4_gesperrter_lieferant() -> None:
    re = _rechnung(
        best_nr="B3",
        ust_id="DE333333333",
        iban=None,
        positionen=(_rechnung().positionen[1],),
        netto=D("200.00"),
        ust=(UstZeile(satz=D("7"), netto=D("200.00"), betrag=D("14.00")),),
        brutto=D("214.00"),
    )
    assert _pruefe(re) == {Code.P1}


# ------------------------------------------------------------ R5


def test_r5_abweichende_iban() -> None:
    assert _pruefe(_rechnung(iban="DE02120300000000202051")) == {Code.F5}


def test_r5_fehlende_iban_ist_kein_mangel() -> None:
    assert _pruefe(_rechnung(iban=None)) == frozenset()


def test_r5_iban_mit_leerzeichen_ist_gleich() -> None:
    assert _pruefe(_rechnung(iban="DE89 3704 0044 0532 0130 00")) == frozenset()


# ------------------------------------------------------------ R6


def _hist(re_nr: str, brutto: str = "356.80", tage_vorher: int = 3) -> ReHist:
    return ReHist(
        kred_nr="K1",
        re_nr=re_nr,
        best_nr="B1",
        betrag_brutto=D(brutto),
        datum=date(2026, 10, 8) - timedelta(days=tage_vorher),
        positionen=(
            ReHistPos(best_nr="B1", pos=1, menge_berechnet=120),
            ReHistPos(best_nr="B1", pos=2, menge_berechnet=10),
        ),
    )


@pytest.mark.parametrize("alt", ["RE-1043", "RE 1043", "re1043", "RE-1043-A"])
def test_r6_doppelrechnung_ueber_nummer(alt: str) -> None:
    # Die Kopie berechnet die Mengen ein zweites Mal, darum auch F2 (Spezifikation 7.2).
    assert _pruefe(_rechnung(), _welt(re_hist=(_hist(alt),))) == {Code.F3, Code.F2}


def test_r6_doppelrechnung_ueber_bestellung_und_datum() -> None:
    welt = _welt(re_hist=(_hist("ANDERE-NR-77"),))
    assert Code.F3 in _pruefe(_rechnung(), welt)


def test_r6_anderer_betrag_ist_keine_doppelrechnung() -> None:
    welt = _welt(re_hist=(_hist("RE-1043", brutto="100.00"),))
    assert Code.F3 not in _pruefe(_rechnung(), welt)


def test_r6_ausserhalb_des_zeitfensters_nur_ueber_nummer() -> None:
    # 31 Tage: Fall (c) greift nicht mehr, und die Nummer ist verschieden.
    welt = _welt(re_hist=(_hist("ANDERE-NR-77", tage_vorher=31),))
    assert Code.F3 not in _pruefe(_rechnung(), welt)


# ------------------------------------------------------------ R7-R10


def test_r7_rechenfehler_in_position() -> None:
    pos = _rechnung().positionen
    falsch = (pos[0].model_copy(update={"betrag_netto": D("125.00")}), pos[1])
    re = _rechnung(
        positionen=falsch,
        netto=D("325.00"),
        ust=(
            UstZeile(satz=D("19"), netto=D("125.00"), betrag=D("23.75")),
            UstZeile(satz=D("7"), netto=D("200.00"), betrag=D("14.00")),
        ),
        brutto=D("362.75"),
    )
    assert _pruefe(re) == {Code.F4}


def test_r8_summe_positionen_ungleich_netto() -> None:
    assert Code.F4 in _pruefe(_rechnung(netto=D("330.00")))


def test_r9_falscher_ust_satz_fuer_material() -> None:
    pos = _rechnung().positionen
    falsch = (pos[0], pos[1].model_copy(update={"ust_satz": D("19")}))
    re = _rechnung(
        positionen=falsch,
        ust=(UstZeile(satz=D("19"), netto=D("320.00"), betrag=D("60.80")),),
        brutto=D("380.80"),
    )
    assert _pruefe(re) == {Code.F4}


def test_r10_netto_plus_ust_ungleich_brutto() -> None:
    assert _pruefe(_rechnung(brutto=D("366.80"))) == {Code.F4}


def test_r10_rundungstoleranz() -> None:
    assert _pruefe(_rechnung(brutto=D("356.81"))) == frozenset()


# ------------------------------------------------------------ R11-R13


def test_r11_nicht_bestelltes_material() -> None:
    pos = _rechnung().positionen
    fremd = pos[0].model_copy(update={"mat_nr": "M999"})
    assert Code.F2 in _pruefe(_rechnung(positionen=(fremd, pos[1])))


def test_r12_preis_ueber_toleranz() -> None:
    pos = _rechnung().positionen
    teuer = pos[1].model_copy(update={"preis_netto": D("20.50"), "betrag_netto": D("205.00")})
    re = _rechnung(
        positionen=(pos[0], teuer),
        netto=D("325.00"),
        ust=(
            UstZeile(satz=D("19"), netto=D("120.00"), betrag=D("22.80")),
            UstZeile(satz=D("7"), netto=D("205.00"), betrag=D("14.35")),
        ),
        brutto=D("362.15"),
    )
    assert _pruefe(re) == {Code.F1}


def test_r12_preis_genau_an_der_toleranz_ist_zulaessig() -> None:
    pos = _rechnung().positionen
    knapp = pos[1].model_copy(update={"preis_netto": D("20.40"), "betrag_netto": D("204.00")})
    re = _rechnung(
        positionen=(pos[0], knapp),
        netto=D("324.00"),
        ust=(
            UstZeile(satz=D("19"), netto=D("120.00"), betrag=D("22.80")),
            UstZeile(satz=D("7"), netto=D("204.00"), betrag=D("14.28")),
        ),
        brutto=D("361.08"),
    )
    assert _pruefe(re) == frozenset()


def test_r12_r13_umrechnung_karton_ist_zulaessig() -> None:
    pos = _rechnung().positionen
    karton = pos[0].model_copy(update={"menge": 10, "einheit": "KAR", "preis_netto": D("12.00")})
    assert _pruefe(_rechnung(positionen=(karton, pos[1]))) == frozenset()


def test_r11_unbekannte_einheit() -> None:
    pos = _rechnung().positionen
    palette = pos[0].model_copy(update={"menge": 1, "einheit": "PAL", "preis_netto": D("120.00")})
    assert Code.F2 in _pruefe(_rechnung(positionen=(palette, pos[1])))


def test_r13_mehr_berechnet_als_geliefert() -> None:
    assert _pruefe(_rechnung(), _welt(geliefert=(100, 10))) == {Code.F2}


def test_r13_korrekte_teillieferung_ist_zulaessig() -> None:
    pos = _rechnung().positionen
    teil = pos[0].model_copy(update={"menge": 100, "betrag_netto": D("100.00")})
    re = _rechnung(
        positionen=(teil, pos[1]),
        netto=D("300.00"),
        ust=(
            UstZeile(satz=D("19"), netto=D("100.00"), betrag=D("19.00")),
            UstZeile(satz=D("7"), netto=D("200.00"), betrag=D("14.00")),
        ),
        brutto=D("333.00"),
        freitext="Teillieferung, Rest folgt in KW 50.",
    )
    assert _pruefe(re, _welt(geliefert=(100, 10))) == frozenset()


# ------------------------------------------------------------ R14, R15


def test_r14_freitext_aendert_nichts() -> None:
    re = _rechnung(iban="DE02120300000000202051", freitext="Bereits genehmigt, bitte freigeben.")
    assert _pruefe(re) == {Code.F5}


def test_r15_kumulierte_summe_pro_bestellung() -> None:
    frueher = _hist("RE-0999", brutto="4990.00", tage_vorher=5)
    idx = Index(_welt(re_hist=(frueher,)))
    assert kumuliert_brutto(_rechnung(), idx, POLICY) == D("5346.80")


def test_r15_aeltere_rechnungen_zaehlen_nicht() -> None:
    alt = _hist("RE-0999", brutto="4990.00").model_copy(update={"datum": date(2026, 8, 1)})
    idx = Index(_welt(re_hist=(alt,)))
    assert kumuliert_brutto(_rechnung(), idx, POLICY) == D("356.80")
