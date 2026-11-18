"""Entscheidungsregel gemäß Spezifikation, Abschnitte 4 und 5."""

import pytest

from invoice_agent.domain import FOLGE, Code, Entscheidung, entscheide


def test_ohne_codes_wird_freigegeben() -> None:
    assert entscheide([]) is Entscheidung.FREIGEBEN


@pytest.mark.parametrize("code", [Code.F1, Code.F2, Code.F3, Code.F4])
def test_mangel_fuehrt_zu_zurueckhalten(code: Code) -> None:
    assert entscheide([code]) is Entscheidung.ZURUECKHALTEN


@pytest.mark.parametrize("code", [Code.F5, Code.F6, Code.P1, Code.P2, Code.P3])
def test_verdacht_fuehrt_zu_eskalieren(code: Code) -> None:
    assert entscheide([code]) is Entscheidung.ESKALIEREN


def test_eskalieren_hat_vorrang_vor_zurueckhalten() -> None:
    assert entscheide([Code.F1, Code.F5]) is Entscheidung.ESKALIEREN


def test_doppelrechnung_mit_mengenfehler_bleibt_zurueckhalten() -> None:
    # Spezifikation 7.2: Eine kopierte Rechnung löst F3 und F2 aus.
    assert entscheide([Code.F3, Code.F2]) is Entscheidung.ZURUECKHALTEN


def test_jeder_code_hat_eine_folge() -> None:
    assert set(FOLGE) == set(Code)


def test_freigeben_ist_nie_folge_eines_codes() -> None:
    assert Entscheidung.FREIGEBEN not in FOLGE.values()
