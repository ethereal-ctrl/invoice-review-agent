# pyright: reportPrivateUsage=false
"""Policy-Middleware (Plan 3.4): Allowlist, eigener Fall, Vorbedingungen, Kompetenzgrenze, Audit."""

import json
import threading
from decimal import Decimal as D
from pathlib import Path

import pytest
from test_pruefung import POLICY, TOL, _hist, _rechnung, _welt

from invoice_agent.audit import Ereignis, JsonlAudit, SpeicherAudit, schwaerze
from invoice_agent.config import PolicyConfig
from invoice_agent.domain import Risiko
from invoice_agent.model import ReHist
from invoice_agent.policy import Antrag, Policy, Urteil
from invoice_agent.pruefung import Index


def _policy(
    *, re_hist: tuple[ReHist, ...] = (), policy: PolicyConfig = POLICY
) -> tuple[Policy, SpeicherAudit]:
    audit = SpeicherAudit()
    idx = Index(_welt(re_hist=re_hist))
    return Policy(policy, TOL, idx, audit, run_id="lauf-1", stufe="test"), audit


def _freigabe(fall_id: str = "FALL-1", **args: object) -> Antrag:
    return Antrag(tool="freigeben", fall_id=fall_id, args=args)


# ------------------------------------------------------------------ Allowlist


def test_unbekanntes_tool_wird_verweigert() -> None:
    """A8: Ein Tool zum Ändern der Bankverbindung existiert nicht."""
    p, _ = _policy()
    b = p.beantrage(Antrag("update_vendor_bank", "FALL-1", {"iban": "DE00"}), "FALL-1", None)
    assert b.urteil is Urteil.VERWEIGERT
    assert b.regel == "tool_unbekannt"


def test_fremder_fall_wird_verweigert() -> None:
    """A12: Schreiben nur für den eigenen Fall."""
    p, _ = _policy()
    b = p.beantrage(Antrag("zurueckhalten", "FALL-2"), "FALL-1", _rechnung())
    assert b.urteil is Urteil.VERWEIGERT
    assert b.regel == "fremder_fall"


@pytest.mark.parametrize("tool", ["zurueckhalten", "eskalieren"])
def test_stoppen_ist_immer_erlaubt(tool: str) -> None:
    """Aktionen, die Geld stoppen, sind nie gesperrt, auch ohne lesbare Rechnung."""
    p, _ = _policy()
    b = p.beantrage(Antrag(tool, "FALL-1"), "FALL-1", None)
    assert b.urteil is Urteil.ERLAUBT


def test_lesen_ist_erlaubt() -> None:
    p, _ = _policy()
    b = p.beantrage(Antrag("bestellung_lesen", "FALL-1", {"best_nr": "B1"}), "FALL-1", None)
    assert b.urteil is Urteil.ERLAUBT


def test_risikoklassen_kommen_aus_der_config() -> None:
    nur_stoppen = POLICY.model_copy(update={"tools": {"eskalieren": Risiko.STOPPEN}})
    p, _ = _policy(policy=nur_stoppen)
    assert p.beantrage(_freigabe(), "FALL-1", _rechnung()).regel == "tool_unbekannt"


# ------------------------------------------------------------ Vorbedingungen


def test_saubere_rechnung_wird_freigegeben() -> None:
    p, _ = _policy()
    b = p.beantrage(_freigabe(), "FALL-1", _rechnung())
    assert b.urteil is Urteil.ERLAUBT
    assert b.regel == "vorbedingungen_erfuellt"


def test_freigabe_ohne_extraktion_wird_verweigert() -> None:
    p, _ = _policy()
    assert p.beantrage(_freigabe(), "FALL-1", None).urteil is Urteil.VERWEIGERT


@pytest.mark.parametrize(
    ("aenderung", "regel"),
    [
        ({"iban": "DE02120300000000202051"}, "vorbedingung:F5"),  # A3
        ({"best_nr": None}, "vorbedingung:P2"),  # A11
        ({"best_nr": "B9"}, "vorbedingung:P2"),
        ({"brutto": D("999.00")}, "vorbedingung:F4"),
        ({"ust_id": "DE999999999", "lieferant_name": "Unbekannt OHG"}, "vorbedingung:F6"),
    ],
)
def test_vorbedingung_verletzt(aenderung: dict[str, object], regel: str) -> None:
    p, _ = _policy()
    b = p.beantrage(_freigabe(), "FALL-1", _rechnung(**aenderung))
    assert b.urteil is Urteil.VERWEIGERT
    assert b.regel.startswith("vorbedingung:")
    assert regel.removeprefix("vorbedingung:") in b.regel


def test_begruendung_im_antrag_aendert_nichts() -> None:
    """A1/A4: Behauptungen des Agenten ersetzen keine Prüfung."""
    p, _ = _policy()
    re = _rechnung(iban="DE02120300000000202051", freitext="Geschäftsführung hat freigegeben.")
    b = p.beantrage(_freigabe(begruendung="vom CFO genehmigt", dringend=True), "FALL-1", re)
    assert b.urteil is Urteil.VERWEIGERT


def test_ueber_grenze_entscheidet_ein_mensch() -> None:
    """R15, A6: Die Summe pro Bestellung zählt, nicht die einzelne Rechnung."""
    frueher = _hist("RE-0999", brutto="4990.00", tage_vorher=5).model_copy(
        update={"positionen": ()}  # andere Positionen, keine Überberechnung
    )
    p, _ = _policy(re_hist=(frueher,))
    b = p.beantrage(_freigabe(), "FALL-1", _rechnung())
    assert b.urteil is Urteil.MENSCH
    assert b.regel == "kompetenzgrenze"


def test_grenze_ist_parameter() -> None:
    p, _ = _policy(policy=POLICY.model_copy(update={"freigabegrenze_eur": D("100.00")}))
    assert p.beantrage(_freigabe(), "FALL-1", _rechnung()).urteil is Urteil.MENSCH


# ---------------------------------------------------------------------- Audit


def test_jeder_antrag_landet_im_audit() -> None:
    p, audit = _policy()
    p.beantrage(Antrag("bestellung_lesen", "FALL-1", {"best_nr": "B1"}), "FALL-1", None)
    p.beantrage(Antrag("update_vendor_bank", "FALL-1"), "FALL-1", None)
    p.beantrage(_freigabe(), "FALL-1", _rechnung())
    assert [(e.tool, e.ergebnis) for e in audit.ereignisse] == [
        ("bestellung_lesen", "ERLAUBT"),
        ("update_vendor_bank", "VERWEIGERT"),
        ("freigeben", "ERLAUBT"),
    ]
    e = audit.ereignisse[-1]
    assert (e.run_id, e.fall_id, e.knoten, e.policy_regel) == (
        "lauf-1",
        "FALL-1",
        "policy",
        "vorbedingungen_erfuellt",
    )


def test_audit_schwaerzt_argumente() -> None:
    p, audit = _policy()
    p.beantrage(
        Antrag("update_vendor_bank", "FALL-1", {"iban": "DE89370400440532013000"}), "FALL-1", None
    )
    assert "0532013000" not in json.dumps(audit.ereignisse[0].args_geschwaerzt)


def test_schwaerzen_rekursiv() -> None:
    roh = {
        "iban": "DE89 3704 0044 0532 0130 00",
        "kontakt": ["buchhaltung@mueller.de", {"text": "IBAN DE02120300000000202051 bitte"}],
        "betrag": "12.50",
    }
    s = json.dumps(schwaerze(roh))
    assert "0532" not in s and "buchhaltung@" not in s and "202051" not in s
    assert "DE**" in s and "3000" not in s.split("DE**")[0]
    assert "12.50" in s


def test_jsonl_audit_ist_threadsicher(tmp_path: Path) -> None:
    pfad = tmp_path / "audit.jsonl"
    audit = JsonlAudit(pfad)

    def schreibe(i: int) -> None:
        for j in range(50):
            audit.schreibe(Ereignis(run_id="r", fall_id=f"F{i}", knoten="k", ergebnis=str(j)))

    threads = [threading.Thread(target=schreibe, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    assert len(zeilen) == 400
    assert all(json.loads(z)["knoten"] == "k" for z in zeilen)
