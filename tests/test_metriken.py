"""Kostenmatrix, Metriken und gepaarter Bootstrap."""

from decimal import Decimal as D
from pathlib import Path

import pytest

from invoice_agent.config import KostenConfig, lade
from invoice_agent.domain import Code, Entscheidung
from invoice_agent.eval.bootstrap import vergleiche
from invoice_agent.eval.metriken import Vorhersage, berechne, ist_unsicher, kosten
from invoice_agent.gold import Gold

F, Z, E = Entscheidung.FREIGEBEN, Entscheidung.ZURUECKHALTEN, Entscheidung.ESKALIEREN
K: KostenConfig = lade(Path(__file__).parents[1] / "configs" / "default.yaml").kosten


def _gold(fall_id: str, typ: str, entscheidung: Entscheidung, codes: tuple[Code, ...] = ()) -> Gold:
    return Gold(
        fall_id=fall_id,
        split="dev",
        smoke=False,
        typ=typ,
        variante=None,
        entscheidung=entscheidung,
        codes=codes,
        brutto=D("1000.00"),
        abweichung_eur=D("0") if entscheidung is F else D("80.00"),
    )


G_OK = _gold("A", "SAUBER", F)
G_Z = _gold("B", "F1", Z, (Code.F1,))
G_E = _gold("C", "F5", E, (Code.F5,))


@pytest.mark.parametrize(
    ("gold", "ist", "erwartet"),
    [
        (G_OK, F, "0"),
        (G_OK, Z, "15.00"),
        (G_OK, E, "5.00"),
        (G_Z, F, "80.00"),  # zu viel gezahlter Betrag
        (G_Z, Z, "0"),
        (G_Z, E, "5.00"),
        (G_E, F, "1000.00"),  # ganzer Rechnungsbetrag
        (G_E, Z, "10.00"),
        (G_E, E, "0"),
    ],
)
def test_kostenmatrix(gold: Gold, ist: Entscheidung, erwartet: str) -> None:
    assert kosten(gold, Vorhersage(fall_id=gold.fall_id, entscheidung=ist), K) == D(erwartet)


def test_interrupt_zaehlt_als_eskalieren() -> None:
    v = Vorhersage(fall_id="A", entscheidung=F, interrupt=True)
    assert v.effektiv is E
    assert kosten(G_OK, v, K) == D("5.00")
    assert not ist_unsicher(G_E, Vorhersage(fall_id="C", entscheidung=F, interrupt=True))


def test_unsicher_nur_bei_freigabe_entgegen_gold() -> None:
    assert ist_unsicher(G_Z, Vorhersage(fall_id="B", entscheidung=F))
    assert not ist_unsicher(G_OK, Vorhersage(fall_id="A", entscheidung=F))
    assert not ist_unsicher(G_Z, Vorhersage(fall_id="B", entscheidung=E))


def test_metriken_immer_freigeben() -> None:
    gold = [G_OK, G_Z, G_E]
    m = berechne(gold, [Vorhersage(fall_id=g.fall_id, entscheidung=F) for g in gold], K)
    assert m.kosten_pro_100 == D("36000.00")  # (0 + 80 + 1000) / 3 * 100
    assert m.unsichere_aktionen == 2
    assert m.genauigkeit == pytest.approx(1 / 3)
    assert m.erkennung_pro_typ == {"F1": 0.0, "F5": 0.0}
    assert m.fehlalarm_pro_typ == {"SAUBER": 0.0}


def test_reale_fehlerquote_gewichtet_fehlerfaelle_herunter() -> None:
    gold = [G_OK, G_Z, G_E]
    m = berechne(gold, [Vorhersage(fall_id=g.fall_id, entscheidung=F) for g in gold], K)
    # Fehlerfälle: 2/3 der Stichprobe, real 5 %: Gewicht 0,075; fehlerfreie: Gewicht 2,85
    assert m.kosten_pro_100_real == D("2700.00")


def test_erkennung_verlangt_den_richtigen_code() -> None:
    v_falscher_code = Vorhersage(fall_id="B", entscheidung=Z, codes=(Code.F4,))
    v_richtig = Vorhersage(fall_id="B", entscheidung=Z, codes=(Code.F1,))
    assert berechne([G_Z], [v_falscher_code], K).erkennung_pro_typ == {"F1": 0.0}
    assert berechne([G_Z], [v_richtig], K).erkennung_pro_typ == {"F1": 1.0}


def test_fehlende_vorhersage_ist_ein_fehler() -> None:
    with pytest.raises(ValueError, match="Keine Vorhersage"):
        berechne([G_OK, G_Z], [Vorhersage(fall_id="A", entscheidung=F)], K)


# ---------------------------------------------------------------- Bootstrap


def _viele(n: int) -> list[Gold]:
    return [_gold(f"Z{i}", "F1", Z, (Code.F1,)) for i in range(n)]


def test_bootstrap_gleiche_laeufe_ohne_unterschied() -> None:
    gold = _viele(50)
    v = [Vorhersage(fall_id=g.fall_id, entscheidung=Z, codes=(Code.F1,)) for g in gold]
    for vgl in vergleiche(gold, v, v, K):
        assert vgl.differenz == 0
        assert not vgl.signifikant


def test_bootstrap_erkennt_klaren_unterschied() -> None:
    gold = _viele(60)
    schlecht = [Vorhersage(fall_id=g.fall_id, entscheidung=F) for g in gold]
    gut = [Vorhersage(fall_id=g.fall_id, entscheidung=Z, codes=(Code.F1,)) for g in gold]
    ergebnis = {vgl.kennzahl: vgl for vgl in vergleiche(gold, schlecht, gut, K)}
    assert ergebnis["genauigkeit"].signifikant
    assert ergebnis["genauigkeit"].differenz == pytest.approx(1.0)
    assert ergebnis["kosten_pro_100"].oben < 0


def test_bootstrap_ist_deterministisch() -> None:
    gold = _viele(40)
    a = [Vorhersage(fall_id=g.fall_id, entscheidung=F if i % 3 else Z) for i, g in enumerate(gold)]
    b = [Vorhersage(fall_id=g.fall_id, entscheidung=Z) for g in gold]
    assert vergleiche(gold, a, b, K) == vergleiche(gold, a, b, K)


def test_metriken_getrennt_nach_layout() -> None:
    a = _gold("A1", "SAUBER", F)
    c = _gold("C1", "SAUBER", F).model_copy(update={"layout": "C"})
    v = [Vorhersage(fall_id="A1", entscheidung=F), Vorhersage(fall_id="C1", entscheidung=E)]
    m = berechne([a, c], v, K)
    assert m.nach_layout["A"]["genauigkeit"] == 1.0
    assert m.nach_layout["C"]["genauigkeit"] == 0.0
    assert m.nach_layout["C"]["kosten_pro_100"] == 500.0


def test_latenz_nur_aus_live_faellen() -> None:
    gold = [_gold(f, "SAUBER", F) for f in ("a", "b", "c")]
    v = [
        Vorhersage(fall_id="a", entscheidung=F, latenz_ms=90_000),
        Vorhersage(fall_id="b", entscheidung=F, latenz_ms=5, aus_cache=True),
        Vorhersage(fall_id="c", entscheidung=F, latenz_ms=7, aus_cache=True),
    ]
    m = berechne(gold, v, K)
    assert m.latenz_p50_ms == 90_000
    assert abs(m.anteil_cache - 2 / 3) < 1e-9
