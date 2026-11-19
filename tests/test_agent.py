"""Stufe 3: LangGraph-Agent mit einem Fake-LLM, das Tool-Aufrufe nach Skript liefert."""

import json
import random
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from langgraph.types import Command

from invoice_agent.audit import SpeicherAudit
from invoice_agent.config import Settings, lade
from invoice_agent.domain import Code, Entscheidung
from invoice_agent.erp import WeltErp
from invoice_agent.generator.faelle import Ergebnis, Fall, erzeuge
from invoice_agent.generator.render import render, waehle_variante
from invoice_agent.llm.client import ChatClient, LlmProfil
from invoice_agent.pruefung import Index, kumuliert_brutto
from invoice_agent.stufen.agent import TOOLS, Agentenstufe
from invoice_agent.stufen.llm_extraktion import LlmExtraktion

CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"
PROFIL = LlmProfil(provider="fake", basis_url="http://fake/v1", modell="m", rpm=10_000)

Aufruf = tuple[str, dict[str, object]]


@pytest.fixture(scope="module")
def settings() -> Settings:
    return lade(CONFIG)


@pytest.fixture(scope="module")
def ergebnis(settings: Settings) -> Ergebnis:
    return erzeuge(settings)


def _fall(ergebnis: Ergebnis, settings: Settings, typ: str, ueber_grenze: bool = False) -> Fall:
    idx = Index(ergebnis.welt)
    grenze = settings.policy.freigabegrenze_eur
    for f in ergebnis.faelle:
        summe = kumuliert_brutto(f.rechnung, idx, settings.policy)
        if f.gold.typ == typ and (summe > grenze) == ueber_grenze:
            return f
    raise LookupError(typ)


class _Skript:
    """Extraktion (ohne Tools) liefert die echte Rechnung; Agent-Aufrufe kommen aus dem Skript."""

    def __init__(self, fall: Fall, schritte: list[list[Aufruf] | str]) -> None:
        self.fall = fall
        self.schritte = schritte
        self.agent_anfragen: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "tools" not in body:
            d = self.fall.rechnung.model_dump(mode="json")
            d.pop("freitext")
            return self._antwort({"content": json.dumps(d)})
        self.agent_anfragen.append(body)
        schritt = self.schritte.pop(0) if self.schritte else "ich bin mir unsicher"
        if isinstance(schritt, str):
            return self._antwort({"content": schritt})
        aufrufe = [
            {"id": f"c{i}", "type": "function",
             "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(schritt)
        ]  # fmt: skip
        return self._antwort({"content": None, "tool_calls": aufrufe})

    @staticmethod
    def _antwort(nachricht: dict[str, object]) -> httpx.Response:
        body = {
            "choices": [{"message": nachricht}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return httpx.Response(200, json=body)


def _stufe(
    tmp_path: Path, settings: Settings, ergebnis: Ergebnis, skript: _Skript
) -> tuple[Agentenstufe, SpeicherAudit, Path]:
    client = ChatClient(PROFIL, tmp_path / "cache", transport=httpx.MockTransport(skript))
    audit = SpeicherAudit()
    stufe = Agentenstufe(
        "agent:fake",
        settings,
        ergebnis.welt,
        client,
        LlmExtraktion(client),
        WeltErp(ergebnis.welt),
        audit,
        "lauf-t",
    )
    pdf = tmp_path / f"{skript.fall.fall_id}.pdf"
    render(skript.fall.rechnung, pdf, waehle_variante(random.Random(0)))
    return stufe, audit, pdf


def test_tools_haben_kein_stammdaten_tool() -> None:
    namen = {t["function"]["name"] for t in TOOLS}
    assert not any("update" in n or "aendern" in n for n in namen)


def test_saubere_rechnung_freigeben(tmp_path: Path, settings: Settings, ergebnis: Ergebnis) -> None:
    fall = _fall(ergebnis, settings, "SAUBER")
    best = fall.rechnung.best_nr
    skript = _Skript(
        fall,
        [
            [("bestellung_lesen", {"best_nr": best}), ("wareneingang_lesen", {"best_nr": best})],
            [("freigeben", {"fall_id": fall.fall_id})],
        ],
    )
    stufe, audit, pdf = _stufe(tmp_path, settings, ergebnis, skript)
    v = stufe.entscheide(fall.fall_id, pdf)
    assert (v.entscheidung, v.interrupt, v.policy_regel) == (
        Entscheidung.FREIGEBEN,
        False,
        "vorbedingungen_erfuellt",
    )
    # Die Lese-Ergebnisse landen als Tool-Antworten im zweiten Aufruf.
    tool_antworten = [m for m in skript.agent_anfragen[1]["messages"] if m["role"] == "tool"]
    assert len(tool_antworten) == 2 and best in tool_antworten[0]["content"]
    assert v.tokens_ein == 30  # Extraktion + zwei Agent-Schritte
    assert [e.knoten for e in audit.ereignisse].count("agent") == 2


def test_policy_verweigert_freigabe_bei_falscher_iban(
    tmp_path: Path, settings: Settings, ergebnis: Ergebnis
) -> None:
    fall = _fall(ergebnis, settings, "F5")
    skript = _Skript(fall, [[("freigeben", {"fall_id": fall.fall_id})]])
    stufe, _, pdf = _stufe(tmp_path, settings, ergebnis, skript)
    v = stufe.entscheide(fall.fall_id, pdf)
    assert v.entscheidung is Entscheidung.ESKALIEREN
    assert v.policy_regel is not None and "F5" in v.policy_regel


def test_unbekanntes_tool_und_fremder_fall(
    tmp_path: Path, settings: Settings, ergebnis: Ergebnis
) -> None:
    fall = _fall(ergebnis, settings, "F1")
    skript = _Skript(
        fall,
        [
            [("update_vendor_bank", {"iban": "DE89370400440532013000"})],
            [("zurueckhalten", {"fall_id": "FALL-9999", "codes": ["F1"]})],
            [("zurueckhalten", {"fall_id": fall.fall_id, "codes": ["F1", "X9"]})],
        ],
    )
    stufe, audit, pdf = _stufe(tmp_path, settings, ergebnis, skript)
    v = stufe.entscheide(fall.fall_id, pdf)
    assert v.entscheidung is Entscheidung.ZURUECKHALTEN
    assert v.codes == (Code.F1,)
    regeln = [e.policy_regel for e in audit.ereignisse if e.knoten == "policy"]
    assert regeln == ["tool_unbekannt", "fremder_fall", "stoppen"]
    assert "verweigert" in skript.agent_anfragen[1]["messages"][-1]["content"]


def test_ueber_grenze_interrupt_und_fortsetzen(
    tmp_path: Path, settings: Settings, ergebnis: Ergebnis
) -> None:
    fall = _fall(ergebnis, settings, "SAUBER", ueber_grenze=True)
    assert fall.rechnung.brutto > Decimal(0)
    skript = _Skript(fall, [[("freigeben", {"fall_id": fall.fall_id})]])
    stufe, audit, pdf = _stufe(tmp_path, settings, ergebnis, skript)
    v = stufe.entscheide(fall.fall_id, pdf)
    assert v.interrupt and v.effektiv is Entscheidung.ESKALIEREN

    # Ein Mensch gibt frei; der Graph läuft am interrupt weiter.
    konfig = stufe.konfig(fall.fall_id)
    stufe.graph.invoke(Command(resume={"freigeben": True}), konfig)
    werte = stufe.graph.get_state(konfig).values
    assert werte["entscheidung"] == "FREIGEBEN"
    assert audit.ereignisse[-1].knoten == "mensch"


def test_ohne_abschluss_greift_das_schrittlimit(
    tmp_path: Path, settings: Settings, ergebnis: Ergebnis
) -> None:
    fall = _fall(ergebnis, settings, "SAUBER")
    stufe, _, pdf = _stufe(tmp_path, settings, ergebnis, _Skript(fall, []))
    v = stufe.entscheide(fall.fall_id, pdf)
    assert v.entscheidung is Entscheidung.ESKALIEREN
    assert v.policy_regel is not None and v.policy_regel.startswith("schrittlimit")


def test_welt_erp_liest_bestellung(ergebnis: Ergebnis) -> None:
    erp = WeltErp(ergebnis.welt)
    b = ergebnis.welt.bestellungen[0]
    antwort = erp.bestellung(b.best_nr)
    assert antwort is not None and antwort["kred_nr"] == b.kred_nr
    assert erp.bestellung("B'; DROP TABLE erp.best_kopf; --") is None
    lf = erp.lieferant(kred_nr=b.kred_nr)
    assert lf is not None and erp.lieferant(ust_id=str(lf["ust_id"]).lower()) == lf
