"""Gemeinsames Ergebnis einer Extraktion, egal ob per Regex oder LLM."""

from dataclasses import dataclass
from decimal import Decimal

from invoice_agent.model import Rechnung


class ExtraktionsFehler(ValueError):
    """Die Rechnung konnte nicht gelesen werden. Die Stufe eskaliert dann (fail-safe)."""


@dataclass(frozen=True)
class Extraktion:
    rechnung: Rechnung
    tokens_ein: int = 0
    tokens_aus: int = 0
    kosten_eur: Decimal = Decimal(0)
    aus_cache: bool = False
