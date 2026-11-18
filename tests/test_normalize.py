"""Normalisierungen gemäß Spezifikation R2, R3, R5, R6."""

import pytest

from invoice_agent.normalize import iban, lieferantenname, rechnungsnr, ust_id


def test_ust_id_ignoriert_leerzeichen_und_schreibweise() -> None:
    assert ust_id(" de 123 456 789 ") == "DE123456789"


def test_iban_ignoriert_leerzeichen_und_schreibweise() -> None:
    assert iban("de89 3704 0044 0532 0130 00") == "DE89370400440532013000"


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        ("RE-1043", "RE1043"),
        ("re 1043", "RE1043"),
        ("RE/1043/A", "RE1043A"),
    ],
)
def test_rechnungsnr_behaelt_nur_buchstaben_und_ziffern(roh: str, erwartet: str) -> None:
    assert rechnungsnr(roh) == erwartet


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Müller GmbH", "Mueller GmbH & Co. KG"),
        ("Weiß Logistik AG", "weiss logistik"),
        ("Bäckerei Schön e.K.", "BAECKEREI SCHOEN"),
        ("Nord-Tech UG (haftungsbeschränkt)", "Nord Tech"),
    ],
)
def test_namensvarianten_sind_gleich(a: str, b: str) -> None:
    assert lieferantenname(a) == lieferantenname(b)


def test_verschiedene_namen_bleiben_verschieden() -> None:
    # A10: Doppelgänger-Lieferant darf nicht über den Namen zusammenfallen.
    assert lieferantenname("Müler GmbH") != lieferantenname("Müller GmbH")
