"""Sensitivität der Kostenmatrix."""

from decimal import Decimal
from pathlib import Path

from invoice_agent.config import lade
from invoice_agent.domain import Entscheidung
from invoice_agent.eval.metriken import Vorhersage
from invoice_agent.eval.sensitivitaet import FAKTOREN, FEHLERQUOTEN, analysiere
from invoice_agent.gold import Gold

CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"
F, Z, E = Entscheidung.FREIGEBEN, Entscheidung.ZURUECKHALTEN, Entscheidung.ESKALIEREN


def _gold(fall_id: str, e: Entscheidung) -> Gold:
    return Gold(
        fall_id=fall_id, split="dev", smoke=False, typ="SAUBER" if e is F else "F1",
        variante=None, entscheidung=e, codes=(), brutto=Decimal("1000"),
        abweichung_eur=Decimal("0") if e is F else Decimal("50"),
    )  # fmt: skip


def test_reihenfolge_und_skalierung() -> None:
    k = lade(CONFIG).kosten
    gold = [_gold("a", F), _gold("b", F), _gold("c", Z)]
    laeufe = {
        "perfekt": [Vorhersage(fall_id=g.fall_id, entscheidung=g.entscheidung) for g in gold],
        "alles_eskalieren": [Vorhersage(fall_id=g.fall_id, entscheidung=E) for g in gold],
    }
    szenarien = analysiere(gold, laeufe, k)
    assert len(szenarien) == len(FAKTOREN) * len(FEHLERQUOTEN)
    assert all(s.rangfolge == "perfekt < alles_eskalieren" for s in szenarien)
    halb = next(s for s in szenarien if s.name == "Pauschalen x0.5, Fehlerquote 5 %")
    doppelt = next(s for s in szenarien if s.name == "Pauschalen x2, Fehlerquote 5 %")
    assert doppelt.kosten["alles_eskalieren"] == 4 * halb.kosten["alles_eskalieren"]
    assert all(s.kosten["perfekt"] == 0 for s in szenarien)


def test_gleichstand_wird_als_gruppe_gezeigt() -> None:
    k = lade(CONFIG).kosten
    gold = [_gold("a", F), _gold("b", Z)]
    gleich = [Vorhersage(fall_id=g.fall_id, entscheidung=g.entscheidung) for g in gold]
    szenarien = analysiere(gold, {"x": gleich, "y": gleich}, k)
    assert szenarien[0].rangfolge == "x = y"
