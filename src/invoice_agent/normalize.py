"""Normalisierungen für Vergleiche (Spezifikation R2, R3, R5, R6)."""

import re

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

# R3: Rechtsformen, nach Normalisierung (Kleinschreibung, Umlaute, Punkte entfernt).
_RECHTSFORMEN = frozenset(
    {"gmbh", "mbh", "co", "kg", "kgaa", "ag", "se", "ohg", "ek", "ug", "haftungsbeschraenkt"}
)


def _ohne_leerzeichen_gross(wert: str) -> str:
    return re.sub(r"\s+", "", wert).upper()


def ust_id(wert: str) -> str:
    """R2: Vergleich ohne Leerzeichen, Großschreibung."""
    return _ohne_leerzeichen_gross(wert)


def iban(wert: str) -> str:
    """R5: Vergleich ohne Leerzeichen, Großschreibung."""
    return _ohne_leerzeichen_gross(wert)


def rechnungsnr(wert: str) -> str:
    """R6: nur Buchstaben und Ziffern, Großschreibung."""
    return re.sub(r"[^0-9A-Za-z]", "", wert).upper()


def lieferantenname(wert: str) -> str:
    """R3: Kleinschreibung, Umlaute, Rechtsformen und Satzzeichen entfernt."""
    text = wert.lower().translate(_UMLAUTE).replace(".", "")
    tokens = re.sub(r"[^0-9a-z]+", " ", text).split()
    return " ".join(t for t in tokens if t not in _RECHTSFORMEN)
