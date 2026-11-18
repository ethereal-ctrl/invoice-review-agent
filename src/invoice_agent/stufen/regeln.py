"""Stufe 1: Regex-Extraktion und Regelwerk, ohne LLM.

Kann eine Rechnung nicht gelesen werden, wird sie eskaliert (fail-safe), nie freigegeben.
Die Kompetenzregel R15 gilt für alle Stufen: Freigaben über der Grenze gehen an einen Menschen.
"""

import time
from collections.abc import Callable
from pathlib import Path

from invoice_agent.config import Settings
from invoice_agent.domain import Entscheidung, entscheide
from invoice_agent.eval.metriken import Vorhersage
from invoice_agent.model import Rechnung, Welt
from invoice_agent.pruefung import Index, kumuliert_brutto, pruefe
from invoice_agent.stufen.regex_extraktion import ExtraktionsFehler, aus_pdf


class Regelstufe:
    """Extraktion austauschbar, Regeln und Policy fest. Stufe 2 nutzt dieselbe Klasse."""

    def __init__(
        self,
        name: str,
        settings: Settings,
        welt: Welt,
        extrahiere: Callable[[Path], Rechnung] = aus_pdf,
    ) -> None:
        self.name = name
        self._settings = settings
        self._idx = Index(welt)
        self._extrahiere = extrahiere

    def entscheide(self, fall_id: str, pdf: Path) -> Vorhersage:
        start = time.perf_counter()
        try:
            re = self._extrahiere(pdf)
        except ExtraktionsFehler as e:
            return Vorhersage(
                fall_id=fall_id,
                entscheidung=Entscheidung.ESKALIEREN,
                extraktion_ok=False,
                fehler=str(e),
                latenz_ms=(time.perf_counter() - start) * 1000,
            )
        codes = pruefe(re, self._idx, self._settings.toleranzen)
        entscheidung = entscheide(codes)
        grenze = self._settings.policy.freigabegrenze_eur
        interrupt = (
            entscheidung is Entscheidung.FREIGEBEN
            and kumuliert_brutto(re, self._idx, self._settings.policy) > grenze
        )
        return Vorhersage(
            fall_id=fall_id,
            entscheidung=entscheidung,
            codes=tuple(sorted(codes)),
            interrupt=interrupt,
            latenz_ms=(time.perf_counter() - start) * 1000,
        )


def regeln(settings: Settings, welt: Welt) -> Regelstufe:
    return Regelstufe("regeln", settings, welt)
