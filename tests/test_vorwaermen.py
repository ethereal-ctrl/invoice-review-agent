"""Vorwärmen: nur Infrastrukturfehler werden wiederholt, nichts aus dem Gold wird gelesen."""

import json
from pathlib import Path

from invoice_agent.domain import Entscheidung
from invoice_agent.eval.metriken import Vorhersage
from invoice_agent.eval.vorwaermen import ist_infrastrukturfehler, speichere_bericht, waerme

E = Entscheidung.ESKALIEREN


class _Wackelig:
    """Fall A scheitert zweimal am Netz, B immer am Modell (Schema), C klappt sofort."""

    name = "wackelig"

    def __init__(self) -> None:
        self.aufrufe: dict[str, int] = {}

    def entscheide(self, fall_id: str, pdf: Path) -> Vorhersage:
        n = self.aufrufe[fall_id] = self.aufrufe.get(fall_id, 0) + 1
        if fall_id == "A" and n <= 2:
            return Vorhersage(fall_id=fall_id, entscheidung=E, policy_regel="llm_fehler|stoppen")
        if fall_id == "B":
            return Vorhersage(
                fall_id=fall_id, entscheidung=E, extraktion_ok=False, fehler="Schema verletzt"
            )
        return Vorhersage(fall_id=fall_id, entscheidung=E, latenz_ms=1000.0)


def test_nur_infrastrukturfehler_werden_wiederholt(tmp_path: Path) -> None:
    stufe = _Wackelig()
    faelle = [(f, tmp_path / f"{f}.pdf") for f in "ABC"]
    b = waerme(stufe, faelle, worker=2, versuche=3, pause_s=0, meldung=lambda _: None)
    assert b.vollstaendig and b.durchgaenge == 3
    assert stufe.aufrufe == {"A": 3, "B": 1, "C": 1}  # Modellfehler werden nicht wiederholt

    pfad = speichere_bericht(tmp_path, "wackelig", "test", b)
    inhalt = json.loads(pfad.read_text(encoding="utf-8"))
    assert inhalt["offen"] == [] and inhalt["latenz_p50_ms"] is not None
    assert "entscheidung" not in pfad.read_text(encoding="utf-8")  # keine Entscheidungen


def test_bleibt_offen_nach_allen_versuchen(tmp_path: Path) -> None:
    stufe = _Wackelig()
    b = waerme(stufe, [("A", tmp_path / "A.pdf")], 1, versuche=2, pause_s=0, meldung=print)
    assert not b.vollstaendig and b.offen == ["A"]


def test_infrastrukturfehler_erkennen() -> None:
    assert ist_infrastrukturfehler(
        Vorhersage(fall_id="x", entscheidung=E, fehler="LLM nicht erreichbar: Timeout")
    )
    assert not ist_infrastrukturfehler(Vorhersage(fall_id="x", entscheidung=E, fehler="Schema"))
