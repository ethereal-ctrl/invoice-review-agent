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


def test_postgres_erp_liefert_dasselbe_wie_welt_erp(tmp_path: Path) -> None:
    """Die Tools des Agenten sehen in Postgres (Rolle ia_agent) exakt dieselben Daten."""
    from invoice_agent.erp import PostgresErp, WeltErp

    ergebnis = erzeuge(lade(CONFIG))
    try:
        owner = psycopg.connect(OWNER_DSN, connect_timeout=2)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres nicht erreichbar: {e}")
    with owner:
        db.lade(owner, ergebnis.welt, [f.fall_id for f in ergebnis.faelle], tmp_path)
    welt, pg = WeltErp(ergebnis.welt), PostgresErp(AGENT_DSN)
    try:
        for b in ergebnis.welt.bestellungen:
            assert pg.bestellung(b.best_nr) == welt.bestellung(b.best_nr)
            assert pg.wareneingang(b.best_nr) == welt.wareneingang(b.best_nr)
        for lf in ergebnis.welt.lieferanten:
            assert pg.lieferant(kred_nr=lf.kred_nr) == welt.lieferant(kred_nr=lf.kred_nr)
            ust = " ".join(lf.ust_id.lower())  # Leerzeichen und Kleinschreibung egal (R2)
            assert pg.lieferant(ust_id=ust) == welt.lieferant(ust_id=ust)
            assert pg.rechnungshistorie(lf.kred_nr) == welt.rechnungshistorie(lf.kred_nr)
        # A9: SQL im Feld der Bestellnummer ist nur ein Suchwert.
        assert pg.bestellung("B1'; DROP TABLE erp.best_kopf; --") is None
        assert pg.lieferant(kred_nr="' OR '1'='1") is None
        assert pg.bestellung(ergebnis.welt.bestellungen[0].best_nr) is not None
    finally:
        pg.schliesse()
