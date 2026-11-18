"""Rechte der Agent-Rolle und Append-only-Audit (Plan 4.3, Angriff A9)."""

import os
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import errors

pytestmark = pytest.mark.db

OWNER_DSN = os.environ.get(
    "IA_OWNER_DSN", "postgresql://ia_owner:ia_owner_dev@localhost:55432/invoice"
)
AGENT_DSN = os.environ.get(
    "IA_AGENT_DSN", "postgresql://ia_agent:ia_agent_dev@localhost:55432/invoice"
)


def _verbinde(dsn: str) -> psycopg.Connection:
    try:
        return psycopg.connect(dsn, connect_timeout=2)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres nicht erreichbar: {e}")


@pytest.fixture
def owner() -> Iterator[psycopg.Connection]:
    with _verbinde(OWNER_DSN) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def agent() -> Iterator[psycopg.Connection]:
    with _verbinde(AGENT_DSN) as conn:
        yield conn
        conn.rollback()


def test_agent_darf_erp_lesen(agent: psycopg.Connection) -> None:
    agent.execute("SELECT count(*) FROM erp.kred_stamm").fetchone()


def test_agent_darf_erp_nicht_schreiben(agent: psycopg.Connection) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute(
            "INSERT INTO erp.kred_stamm (kred_nr, name, ust_id, iban) VALUES ('X', 'X', 'X', 'X')"
        )


def test_agent_darf_stammdaten_iban_nicht_aendern(agent: psycopg.Connection) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("UPDATE erp.kred_stamm SET iban = 'DE00'")


def test_agent_darf_audit_einfuegen(agent: psycopg.Connection) -> None:
    agent.execute(
        "INSERT INTO audit.ereignisse (run_id, knoten, ergebnis) VALUES ('t', 'test', 'ok')"
    )


def test_agent_darf_audit_nicht_lesen(agent: psycopg.Connection) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("SELECT * FROM audit.ereignisse")


def test_agent_darf_audit_nicht_loeschen(agent: psycopg.Connection) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("DELETE FROM audit.ereignisse")


def test_audit_ist_auch_fuer_owner_append_only(owner: psycopg.Connection) -> None:
    owner.execute(
        "INSERT INTO audit.ereignisse (run_id, knoten, ergebnis) VALUES ('t', 'test', 'ok')"
    )
    with pytest.raises(errors.RaiseException):
        owner.execute("UPDATE audit.ereignisse SET ergebnis = 'manipuliert'")


def test_agent_kann_keine_tabellen_anlegen(agent: psycopg.Connection) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        agent.execute("CREATE TABLE app.fremd (x int)")
