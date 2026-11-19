"""Postgres-Queue und Worker gegen die echte Datenbank (Rolle ia_agent)."""

import os
import random
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from invoice_agent import db, queue
from invoice_agent.audit import PostgresAudit
from invoice_agent.config import Settings, lade
from invoice_agent.eval.metriken import Vorhersage
from invoice_agent.generator.faelle import Ergebnis, erzeuge
from invoice_agent.generator.render import render, waehle_variante
from invoice_agent.stufen.regeln import regeln

pytestmark = pytest.mark.db

CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"
OWNER_DSN = os.environ.get(
    "IA_OWNER_DSN", "postgresql://ia_owner:ia_owner_dev@localhost:55432/invoice"
)
AGENT_DSN = os.environ.get(
    "IA_AGENT_DSN", "postgresql://ia_agent:ia_agent_dev@localhost:55432/invoice"
)
ANZAHL = 24


@pytest.fixture(scope="module")
def settings() -> Settings:
    return lade(CONFIG)


@pytest.fixture(scope="module")
def ergebnis(settings: Settings) -> Ergebnis:
    return erzeuge(settings)


@pytest.fixture(scope="module")
def eingang(ergebnis: Ergebnis, tmp_path_factory: pytest.TempPathFactory) -> Path:
    ordner = tmp_path_factory.mktemp("eingang")
    for f in ergebnis.faelle[:ANZAHL]:
        render(f.rechnung, ordner / f"{f.fall_id}.pdf", waehle_variante(random.Random(f.fall_id)))
    return ordner


@pytest.fixture
def owner(ergebnis: Ergebnis, eingang: Path) -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(OWNER_DSN, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres nicht erreichbar: {e}")
    with conn:
        db.lade(conn, ergebnis.welt, [f.fall_id for f in ergebnis.faelle[:ANZAHL]], eingang)
        yield conn


def _status(owner: psycopg.Connection) -> dict[str, int]:
    return dict(owner.execute("SELECT status, count(*) FROM app.faelle GROUP BY status").fetchall())


def test_welt_aus_der_datenbank(owner: psycopg.Connection, ergebnis: Ergebnis) -> None:
    with psycopg.connect(AGENT_DSN) as conn:
        welt = queue.lies_welt(conn)
    erwartet = ergebnis.welt
    assert set(welt.bestellungen) == set(erwartet.bestellungen)
    assert set(welt.wareneingaenge) == set(erwartet.wareneingaenge)
    assert set(welt.re_hist) == set(erwartet.re_hist)
    # Material enthält ein dict und ist nicht hashbar; Decimal("7.00") == Decimal("7").
    assert sorted(welt.materialien, key=lambda m: m.mat_nr) == sorted(
        erwartet.materialien, key=lambda m: m.mat_nr
    )
    ohne_adresse = [lf.model_copy(update={"strasse": "", "ort": ""}) for lf in erwartet.lieferanten]
    assert sorted(welt.lieferanten, key=lambda lf: lf.kred_nr) == sorted(
        ohne_adresse, key=lambda lf: lf.kred_nr
    )


def test_skip_locked_gibt_gesperrte_faelle_nicht_heraus(owner: psycopg.Connection) -> None:
    with psycopg.connect(OWNER_DSN) as sperre, psycopg.connect(AGENT_DSN) as agent:
        gesperrt = sperre.execute(
            "SELECT fall_id FROM app.faelle WHERE status = 'offen' "
            "ORDER BY erstellt, fall_id LIMIT 1 FOR UPDATE"
        ).fetchone()
        assert gesperrt is not None
        fall = queue.hole_fall(agent)  # wartet nicht, nimmt den nächsten
        assert fall is not None and fall[0] != gesperrt[0]
        sperre.rollback()


def test_worker_arbeitet_alles_genau_einmal_ab(
    owner: psycopg.Connection, settings: Settings, ergebnis: Ergebnis, eingang: Path
) -> None:
    with psycopg.connect(AGENT_DSN) as conn:
        welt = queue.lies_welt(conn)
    run_id = f"test-worker-{os.getpid()}"
    audit = PostgresAudit(AGENT_DSN)
    try:
        bilanz = queue.arbeite(AGENT_DSN, regeln(settings, welt, audit, run_id), run_id, threads=6)
    finally:
        audit.schliesse()

    assert len(bilanz.erledigt) == ANZAHL and len(set(bilanz.erledigt)) == ANZAHL
    assert _status(owner) == {"erledigt": ANZAHL}
    zeilen = owner.execute(
        "SELECT fall_id, entscheidung FROM app.entscheidungen WHERE run_id = %s", (run_id,)
    ).fetchall()
    assert len(zeilen) == ANZAHL

    # Gleiche Entscheidungen wie die Stufe direkt auf der Welt aus den Dateien
    direkt = regeln(settings, ergebnis.welt)
    for fall_id, entscheidung in zeilen:
        assert direkt.entscheide(fall_id, eingang / f"{fall_id}.pdf").effektiv.value == entscheidung
    protokoll = owner.execute(
        "SELECT count(*) FROM audit.ereignisse WHERE run_id = %s", (run_id,)
    ).fetchone()
    assert protokoll == (ANZAHL,)


class _Kaputt:
    name = "kaputt"

    def entscheide(self, fall_id: str, pdf: Path) -> Vorhersage:
        raise RuntimeError("Absturz")


def test_fehler_werden_wiederholt_und_dann_markiert(owner: psycopg.Connection) -> None:
    """Jeder Fall wird bis zu MAX_VERSUCHE-mal versucht und landet dann auf `fehler`."""
    bilanz = queue.arbeite(AGENT_DSN, _Kaputt(), "kaputt", threads=2)
    assert len(bilanz.fehler) == ANZAHL * queue.MAX_VERSUCHE
    assert _status(owner) == {"fehler": ANZAHL}
    versuche = owner.execute("SELECT DISTINCT versuche FROM app.faelle").fetchall()
    assert versuche == [(queue.MAX_VERSUCHE,)]


def test_haengende_faelle_werden_wieder_geoeffnet(owner: psycopg.Connection) -> None:
    with psycopg.connect(AGENT_DSN) as agent:
        fall = queue.hole_fall(agent)
        assert fall is not None
        assert queue.gib_haengende_frei(agent, minuten=30) == 0
        owner.execute(
            "UPDATE app.faelle SET locked_at = now() - interval '2 hours' WHERE fall_id = %s",
            (fall[0],),
        )
        assert queue.gib_haengende_frei(agent, minuten=30) == 1
    assert _status(owner) == {"offen": ANZAHL}
