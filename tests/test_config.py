from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from invoice_agent.config import GeneratorConfig, lade

DEFAULT = Path(__file__).parents[1] / "configs" / "default.yaml"


def test_default_config_entspricht_spezifikation() -> None:
    s = lade(DEFAULT)
    assert s.toleranzen.preis_prozent == Decimal("2.0")
    assert s.toleranzen.betrag_eur == Decimal("0.01")
    assert s.policy.freigabegrenze_eur == Decimal("5000.00")
    assert s.generator.anzahl == 300


def test_splits_muessen_aufgehen() -> None:
    with pytest.raises(ValidationError):
        GeneratorConfig(seed=1, anzahl=300, dev=100, test=150, smoke=30)


def test_smoke_muss_in_dev_passen() -> None:
    with pytest.raises(ValidationError):
        GeneratorConfig(seed=1, anzahl=300, dev=100, test=200, smoke=150)
