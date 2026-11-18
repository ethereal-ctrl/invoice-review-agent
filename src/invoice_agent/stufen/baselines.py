"""Triviale Baselines B0 und B1: Jede echte Stufe muss beide schlagen."""

from pathlib import Path

from invoice_agent.domain import Entscheidung
from invoice_agent.eval.metriken import Vorhersage


class ImmerFreigeben:
    name = "b0"

    def entscheide(self, fall_id: str, pdf: Path) -> Vorhersage:
        return Vorhersage(fall_id=fall_id, entscheidung=Entscheidung.FREIGEBEN)


class ImmerEskalieren:
    name = "b1"

    def entscheide(self, fall_id: str, pdf: Path) -> Vorhersage:
        return Vorhersage(fall_id=fall_id, entscheidung=Entscheidung.ESKALIEREN)
