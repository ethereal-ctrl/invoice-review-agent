"""Laden der generierten Welt in Postgres und Sicht der Agent-Rolle darauf."""

import os
from pathlib import Path

import psycopg
import pytest

from invoice_agent import db
from invoice_agent.config import lade
from invoice_agent.generator.faelle import erzeuge

pytestmark = pytest.mark.db

CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"
OWNER_DSN = os.environ.get(
    "IA_OWNER_DSN", "postgresql://ia_owner:ia_owner_dev@localhost:55432/invoice"
)
AGENT_DSN = os.environ.get(
    "IA_AGENT_DSN", "postgresql://ia_agent:ia_agent_dev@localhost:55432/invoice"
)


def test_laden_und_als_agent_lesen(tmp_path: Path) -> None:
    ergebnis = erzeuge(lade(CONFIG))
    try:
        owner = psycopg.connect(OWNER_DSN, connect_timeout=2)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres nicht erreichbar: {e}")
    with owner:
        db.lade(owner, ergebnis.welt, [f.fall_id for f in ergebnis.faelle], tmp_path)

    with psycopg.connect(AGENT_DSN) as agent:
        anzahl = agent.execute("SELECT count(*) FROM app.faelle").fetchone()
        assert anzahl == (300,)
        offene = agent.execute("SELECT count(*) FROM app.faelle WHERE status = 'offen'").fetchone()
        assert offene == (300,)
        lieferanten = agent.execute("SELECT count(*) FROM erp.kred_stamm").fetchone()
        assert lieferanten == (len(ergebnis.welt.lieferanten),)
        # Gold-Labels liegen nicht in der Datenbank: Es gibt keine Spalte dafür.
        spalten = agent.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema IN ('erp', 'app')"
        ).fetchall()
        namen = {s[0] for s in spalten}
        assert not namen & {"typ", "gold", "codes", "abweichung_eur"}
