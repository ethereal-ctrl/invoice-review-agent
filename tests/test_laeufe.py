from decimal import Decimal
from pathlib import Path

import pytest

from invoice_agent.domain import Entscheidung
from invoice_agent.eval.laeufe import SplitBereitsVerwendet, lade_vorhersagen, speichere
from invoice_agent.eval.metriken import Metriken, Vorhersage

V = [Vorhersage(fall_id="A", entscheidung=Entscheidung.FREIGEBEN)]
M = Metriken(
    anzahl=1,
    kosten_pro_100=Decimal(0),
    kosten_pro_100_real=Decimal(0),
    token_kosten_pro_100=Decimal(0),
    genauigkeit=1.0,
    unsichere_aktionen=0,
    rate_unsicher=0.0,
    last_mensch=0.0,
    automatisierung=1.0,
    interrupt_rate=0.0,
    extraktion_fehler=0,
    erkennung_pro_typ={},
    fehlalarm_pro_typ={},
    latenz_p50_ms=0.0,
    latenz_p95_ms=0.0,
)


def test_lauf_wird_gespeichert_und_geladen(tmp_path: Path) -> None:
    ordner = speichere(tmp_path, "b0", "dev", V, M, {})
    assert lade_vorhersagen(ordner) == V


def test_dev_darf_beliebig_oft_laufen(tmp_path: Path) -> None:
    speichere(tmp_path, "b0", "dev", V, M, {"n": 1})
    import time

    time.sleep(1.1)
    speichere(tmp_path, "b0", "dev", V, M, {"n": 2})


def test_test_split_nur_einmal_pro_stufe(tmp_path: Path) -> None:
    speichere(tmp_path, "regeln", "test", V, M, {})
    with pytest.raises(SplitBereitsVerwendet):
        speichere(tmp_path, "regeln", "test", V, M, {})
    speichere(tmp_path, "b0", "test", V, M, {})  # andere Stufe ist erlaubt
