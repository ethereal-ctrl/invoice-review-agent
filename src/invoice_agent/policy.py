"""Policy-Middleware (Plan 3.4, ADR 0004): Regeln stehen im Code, nicht im Prompt.

Jede Stufe, auch der Agent in Stufe 3, darf nur über `Policy.beantrage` handeln. Die Policy
glaubt dem Antragsteller nichts: Begründungen im Antrag werden ignoriert, und für eine
Freigabe prüft sie die Vorbedingungen selbst mit dem deterministischen Regelwerk nach.

Reihenfolge der Prüfung:
1. Tool steht nicht in der Allowlist         -> VERWEIGERT (`tool_unbekannt`, Angriff A8)
2. Antrag betrifft einen anderen Fall         -> VERWEIGERT (`fremder_fall`, A12)
3. Risikoklasse LESEN oder STOPPEN            -> ERLAUBT (Geld stoppen ist nie gesperrt)
4. FREIGEBEN ohne gelesene Rechnung           -> VERWEIGERT (`keine_extraktion`)
5. Regelwerk findet einen Code (F1-F6, P1-P3) -> VERWEIGERT (`vorbedingung:<Codes>`)
6. Kumuliert über der Freigabegrenze (R15)    -> MENSCH (`kompetenzgrenze`, `interrupt`)
7. sonst                                      -> ERLAUBT (`vorbedingungen_erfuellt`)
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from invoice_agent.audit import Audit, Ereignis, schwaerze
from invoice_agent.config import PolicyConfig, Toleranzen
from invoice_agent.domain import Risiko
from invoice_agent.model import Rechnung
from invoice_agent.pruefung import Index, kumuliert_brutto, pruefe


class Urteil(StrEnum):
    ERLAUBT = "ERLAUBT"
    MENSCH = "MENSCH"  # ein Mensch muss freigeben (LangGraph: interrupt)
    VERWEIGERT = "VERWEIGERT"


@dataclass(frozen=True)
class Antrag:
    tool: str
    fall_id: str
    args: Mapping[str, object] = field(default_factory=dict[str, object])


@dataclass(frozen=True)
class Bescheid:
    urteil: Urteil
    regel: str
    grund: str = ""


class Policy:
    def __init__(
        self,
        policy: PolicyConfig,
        toleranzen: Toleranzen,
        idx: Index,
        audit: Audit,
        run_id: str,
        stufe: str,
    ) -> None:
        self._policy = policy
        self._tol = toleranzen
        self._idx = idx
        self._audit = audit
        self.run_id = run_id
        self.stufe = stufe

    def beantrage(self, antrag: Antrag, fall_id: str, rechnung: Rechnung | None) -> Bescheid:
        """Antrag prüfen und protokollieren. `fall_id` ist der Fall, an dem gerade gearbeitet
        wird; `rechnung` ist die Extraktion dieses Falls (None, wenn sie fehlgeschlagen ist)."""
        bescheid = self._urteil(antrag, fall_id, rechnung)
        self._audit.schreibe(
            Ereignis(
                run_id=self.run_id,
                fall_id=fall_id,
                knoten="policy",
                tool=antrag.tool,
                args_geschwaerzt=schwaerze(dict(antrag.args)),
                policy_regel=bescheid.regel,
                ergebnis=bescheid.urteil.value,
                modell=self.stufe,
            )
        )
        return bescheid

    def _urteil(self, antrag: Antrag, fall_id: str, rechnung: Rechnung | None) -> Bescheid:
        risiko = self._policy.tools.get(antrag.tool)
        if risiko is None:
            return Bescheid(Urteil.VERWEIGERT, "tool_unbekannt", f"Tool {antrag.tool!r} fehlt")
        if antrag.fall_id != fall_id:
            return Bescheid(Urteil.VERWEIGERT, "fremder_fall", f"{antrag.fall_id} != {fall_id}")
        if risiko is not Risiko.FREIGEBEN:
            return Bescheid(Urteil.ERLAUBT, risiko.value.lower())
        if rechnung is None:
            return Bescheid(Urteil.VERWEIGERT, "keine_extraktion")
        codes = pruefe(rechnung, self._idx, self._tol)
        if codes:
            liste = ",".join(sorted(codes))
            return Bescheid(Urteil.VERWEIGERT, f"vorbedingung:{liste}")
        summe = kumuliert_brutto(rechnung, self._idx, self._policy)
        if summe > self._policy.freigabegrenze_eur:
            grenze = self._policy.freigabegrenze_eur
            return Bescheid(Urteil.MENSCH, "kompetenzgrenze", f"{summe} > {grenze} EUR")
        return Bescheid(Urteil.ERLAUBT, "vorbedingungen_erfuellt")
