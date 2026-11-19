"""Entscheidungen und Begründungscodes (Spezifikation, Abschnitte 1, 4 und 5)."""

from collections.abc import Iterable
from enum import StrEnum


class Entscheidung(StrEnum):
    FREIGEBEN = "FREIGEBEN"
    ZURUECKHALTEN = "ZURUECKHALTEN"
    ESKALIEREN = "ESKALIEREN"


class Risiko(StrEnum):
    """Risikoklasse eines Tools (Plan 3.4)."""

    LESEN = "LESEN"  # ERP lesen: automatisch
    STOPPEN = "STOPPEN"  # Zurückhalten, Eskalieren: Geld stoppen ist nie gesperrt
    FREIGEBEN = "FREIGEBEN"  # Zahlung freigeben: nur mit Vorbedingungen und unter der Grenze


class Code(StrEnum):
    F1 = "F1"  # Preisabweichung über Toleranz
    F2 = "F2"  # Mehr berechnet als geliefert, oder Position nicht bestellt
    F3 = "F3"  # Verdacht auf Doppelrechnung
    F4 = "F4"  # Steuer- oder Rechenfehler
    F5 = "F5"  # IBAN weicht von den Stammdaten ab
    F6 = "F6"  # Lieferant unklar oder unbekannt
    P1 = "P1"  # Lieferant gesperrt
    P2 = "P2"  # Bestellbezug fehlt oder unbekannt
    P3 = "P3"  # Freigabegrenze pro Bestellung überschritten


FOLGE: dict[Code, Entscheidung] = {
    Code.F1: Entscheidung.ZURUECKHALTEN,
    Code.F2: Entscheidung.ZURUECKHALTEN,
    Code.F3: Entscheidung.ZURUECKHALTEN,
    Code.F4: Entscheidung.ZURUECKHALTEN,
    Code.F5: Entscheidung.ESKALIEREN,
    Code.F6: Entscheidung.ESKALIEREN,
    Code.P1: Entscheidung.ESKALIEREN,
    Code.P2: Entscheidung.ESKALIEREN,
    Code.P3: Entscheidung.ESKALIEREN,
}


def entscheide(codes: Iterable[Code]) -> Entscheidung:
    """Abschnitt 5: ESKALIEREN vor ZURUECKHALTEN vor FREIGEBEN."""
    folgen = {FOLGE[c] for c in codes}
    if Entscheidung.ESKALIEREN in folgen:
        return Entscheidung.ESKALIEREN
    if Entscheidung.ZURUECKHALTEN in folgen:
        return Entscheidung.ZURUECKHALTEN
    return Entscheidung.FREIGEBEN
