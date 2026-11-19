"""Stufe 1: Regex-Extraktion und Regelwerk, ohne LLM.

Kann eine Rechnung nicht gelesen werden, wird sie eskaliert (fail-safe), nie freigegeben.
Jede Aktion geht als Antrag durch die Policy-Middleware. Sie setzt die Kompetenzregel R15
durch (Freigaben über der Grenze gehen an einen Menschen) und protokolliert ins Audit-Log.
"""

import time
from collections.abc import Callable
from pathlib import Path

from invoice_agent.audit import Audit, SpeicherAudit
from invoice_agent.config import Settings
from invoice_agent.domain import Entscheidung, entscheide
from invoice_agent.eval.metriken import Vorhersage
from invoice_agent.model import Welt
from invoice_agent.policy import Antrag, Policy, Urteil
from invoice_agent.pruefung import Index, pruefe
from invoice_agent.stufen.extraktion import Extraktion, ExtraktionsFehler
from invoice_agent.stufen.regex_extraktion import regex_extraktion

TOOL: dict[Entscheidung, str] = {
    Entscheidung.FREIGEBEN: "freigeben",
    Entscheidung.ZURUECKHALTEN: "zurueckhalten",
    Entscheidung.ESKALIEREN: "eskalieren",
}


class Regelstufe:
    """Extraktion austauschbar, Regeln und Policy fest. Stufe 2 nutzt dieselbe Klasse."""

    def __init__(
        self,
        name: str,
        settings: Settings,
        welt: Welt,
        extrahiere: Callable[[Path], Extraktion] = regex_extraktion,
        audit: Audit | None = None,
        run_id: str = "lokal",
    ) -> None:
        self.name = name
        self._settings = settings
        self._idx = Index(welt)
        self._extrahiere = extrahiere
        self._policy = Policy(
            settings.policy,
            settings.toleranzen,
            self._idx,
            audit if audit is not None else SpeicherAudit(),
            run_id,
            name,
        )

    def entscheide(self, fall_id: str, pdf: Path) -> Vorhersage:
        start = time.perf_counter()
        try:
            ex = self._extrahiere(pdf)
        except ExtraktionsFehler as e:
            bescheid = self._policy.beantrage(
                Antrag("eskalieren", fall_id, {"grund": "extraktion_fehlgeschlagen"}), fall_id, None
            )
            return Vorhersage(
                fall_id=fall_id,
                entscheidung=Entscheidung.ESKALIEREN,
                extraktion_ok=False,
                fehler=str(e),
                policy_regel=bescheid.regel,
                latenz_ms=(time.perf_counter() - start) * 1000,
            )
        re = ex.rechnung
        codes = pruefe(re, self._idx, self._settings.toleranzen)
        entscheidung = entscheide(codes)
        antrag = Antrag(TOOL[entscheidung], fall_id, {"codes": sorted(codes)})
        bescheid = self._policy.beantrage(antrag, fall_id, re)
        if bescheid.urteil is Urteil.VERWEIGERT:  # fail-safe: was nicht erlaubt ist, eskaliert
            entscheidung = Entscheidung.ESKALIEREN
        interrupt = bescheid.urteil is Urteil.MENSCH
        return Vorhersage(
            fall_id=fall_id,
            entscheidung=entscheidung,
            codes=tuple(sorted(codes)),
            interrupt=interrupt,
            policy_regel=bescheid.regel,
            brutto=re.brutto,
            aus_cache=ex.aus_cache,
            tokens_ein=ex.tokens_ein,
            tokens_aus=ex.tokens_aus,
            kosten_tokens_eur=ex.kosten_eur,
            latenz_ms=(time.perf_counter() - start) * 1000,
        )


def regeln(
    settings: Settings, welt: Welt, audit: Audit | None = None, run_id: str = "lokal"
) -> Regelstufe:
    return Regelstufe("regeln", settings, welt, regex_extraktion, audit, run_id)


def llm(
    name: str,
    settings: Settings,
    welt: Welt,
    extrahiere: Callable[[Path], Extraktion],
    audit: Audit | None = None,
    run_id: str = "lokal",
) -> Regelstufe:
    """Stufe 2: LLM-Extraktion, danach dieselben Regeln und dieselbe Policy wie Stufe 1."""
    return Regelstufe(name, settings, welt, extrahiere, audit, run_id)
