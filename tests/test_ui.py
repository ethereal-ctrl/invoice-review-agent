"""Freigabe-Cockpit gegen die echte Datenbank (Rolle ia_mensch)."""

import os
import random
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from invoice_agent import db, queue
from invoice_agent.config import Settings, lade
from invoice_agent.generator.faelle import Ergebnis, erzeuge
from invoice_agent.generator.render import render, waehle_variante
from invoice_agent.stufen.regeln import regeln
from invoice_agent.ui.app import erstelle_app

pytestmark = pytest.mark.db

CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"
OWNER_DSN = os.environ.get(
    "IA_OWNER_DSN", "postgresql://ia_owner:ia_owner_dev@localhost:55432/invoice"
)
AGENT_DSN = os.environ.get(
    "IA_AGENT_DSN", "postgresql://ia_agent:ia_agent_dev@localhost:55432/invoice"
)
MENSCH_DSN = os.environ.get(
    "IA_MENSCH_DSN", "postgresql://ia_mensch:ia_mensch_dev@localhost:55432/invoice"
)
ANZAHL = 24


@pytest.fixture(scope="module")
def settings() -> Settings:
    return lade(CONFIG)


@pytest.fixture(scope="module")
def ergebnis(settings: Settings) -> Ergebnis:
    return erzeuge(settings)


@pytest.fixture
def daten(ergebnis: Ergebnis, tmp_path: Path) -> Path:
    eingang = tmp_path / "eingang"
    for f in ergebnis.faelle[:ANZAHL]:
        render(f.rechnung, eingang / f"{f.fall_id}.pdf", waehle_variante(random.Random(f.fall_id)))
    return tmp_path


@pytest.fixture
def client(
    settings: Settings, ergebnis: Ergebnis, daten: Path, tmp_path: Path
) -> Iterator[tuple[TestClient, psycopg.Connection, str]]:
    try:
        owner = psycopg.connect(OWNER_DSN, connect_timeout=2, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"Postgres nicht erreichbar: {e}")
    with owner:
        ids = [f.fall_id for f in ergebnis.faelle[:ANZAHL]]
        db.lade(owner, ergebnis.welt, ids, (daten / "eingang").resolve())
        run_id = f"test-ui-{os.getpid()}"
        queue.arbeite(AGENT_DSN, regeln(settings, ergebnis.welt), run_id, threads=4)
        app = erstelle_app(MENSCH_DSN, settings, daten.resolve(), tmp_path / "runs")
        yield TestClient(app), owner, run_id


def _wartend(owner: psycopg.Connection) -> str:
    zeile = owner.execute(
        "SELECT fall_id FROM app.faelle WHERE status = 'wartet_auf_mensch' ORDER BY fall_id"
    ).fetchone()
    assert zeile is not None
    return str(zeile[0])


def test_uebersicht_zeigt_offene_freigaben(
    client: tuple[TestClient, psycopg.Connection, str],
) -> None:
    c, owner, _ = client
    r = c.get("/")
    assert r.status_code == 200
    assert "Wartet auf Freigabe" in r.text and _wartend(owner) in r.text


def test_fall_mit_spur_und_pdf(client: tuple[TestClient, psycopg.Connection, str]) -> None:
    c, owner, _ = client
    fall_id = _wartend(owner)
    r = c.get(f"/fall/{fall_id}")
    assert r.status_code == 200
    assert "kompetenzgrenze" in r.text and "Freigeben" in r.text
    pdf = c.get(f"/fall/{fall_id}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert c.get("/fall/GIBTSNICHT").status_code == 404


def test_freigabe_per_htmx(client: tuple[TestClient, psycopg.Connection, str]) -> None:
    c, owner, run_id = client
    fall_id = _wartend(owner)
    kopf = {"HX-Request": "true"}
    ohne_name = c.post(f"/fall/{fall_id}/entscheidung", data={"aktion": "freigeben"}, headers=kopf)
    assert ohne_name.status_code == 409

    r = c.post(
        f"/fall/{fall_id}/entscheidung",
        data={"aktion": "zurueckhalten", "name": "S. Prüfer"},
        headers=kopf,
    )
    assert r.status_code == 200 and "ZURUECKHALTEN" in r.text
    status = owner.execute("SELECT status FROM app.faelle WHERE fall_id = %s", (fall_id,))
    assert status.fetchone() == ("erledigt",)
    nochmal = c.post(
        f"/fall/{fall_id}/entscheidung", data={"aktion": "freigeben", "name": "X"}, headers=kopf
    )
    assert nochmal.status_code == 409

    audit = c.get("/audit", params={"fall_id": fall_id, "run_id": run_id})
    assert audit.status_code == 200 and "mensch" in audit.text


def test_unbekannte_aktion(client: tuple[TestClient, psycopg.Connection, str]) -> None:
    c, owner, _ = client
    r = c.post(f"/fall/{_wartend(owner)}/entscheidung", data={"aktion": "loeschen", "name": "X"})
    assert r.status_code == 400


def test_pdf_ausserhalb_des_datenordners_wird_nicht_ausgeliefert(
    client: tuple[TestClient, psycopg.Connection, str],
) -> None:
    c, owner, _ = client
    owner.execute("UPDATE app.faelle SET pdf_pfad = '/etc/passwd' WHERE fall_id = 'FALL-0001'")
    assert c.get("/fall/FALL-0001/pdf").status_code == 404
    owner.execute(
        "UPDATE app.faelle SET pdf_pfad = '/tmp/../etc/hosts.pdf' WHERE fall_id = 'FALL-0001'"
    )
    assert c.get("/fall/FALL-0001/pdf").status_code == 404
