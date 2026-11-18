"""Gemeinsame Schnittstelle aller Stufen der Eval-Ladder.

Stufen dürfen die PDFs und die ERP-Daten sehen, aber nie Gold-Labels, wahre
Rechnungsdaten oder Generator-Code (ADR 0001). Ein Test prüft die Importe.
"""

from pathlib import Path
from typing import Protocol

from invoice_agent.eval.metriken import Vorhersage


class Stufe(Protocol):
    name: str

    def entscheide(self, fall_id: str, pdf: Path) -> Vorhersage: ...
