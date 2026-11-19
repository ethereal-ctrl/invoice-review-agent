"""Generierte Welt und Fälle in Postgres laden (als Owner, nie als Agent)."""

from pathlib import Path

import psycopg

from invoice_agent.model import Welt

_TABELLEN = (
    "app.freigaben, app.entscheidungen, app.faelle, erp.re_hist_pos, erp.re_hist, erp.we_pos, "
    "erp.best_pos, erp.best_kopf, erp.mat_einh, erp.mat_stamm, erp.kred_stamm"
)


def lade(conn: psycopg.Connection, welt: Welt, fall_ids: list[str], eingang: Path) -> None:
    """Ersetzt den gesamten Inhalt von erp und app. Das Audit-Log bleibt unangetastet."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"TRUNCATE {_TABELLEN}")  # feste Tabellenliste, keine Eingabe
        cur.executemany(
            "INSERT INTO erp.kred_stamm (kred_nr, name, ust_id, iban, gesperrt) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(lf.kred_nr, lf.name, lf.ust_id, lf.iban, lf.gesperrt) for lf in welt.lieferanten],
        )
        cur.executemany(
            "INSERT INTO erp.mat_stamm (mat_nr, bezeichnung, basis_einheit, ust_satz) "
            "VALUES (%s, %s, %s, %s)",
            [(m.mat_nr, m.bezeichnung, m.basis_einheit, m.ust_satz) for m in welt.materialien],
        )
        cur.executemany(
            "INSERT INTO erp.mat_einh (mat_nr, einheit, faktor) VALUES (%s, %s, %s)",
            [(m.mat_nr, e, f) for m in welt.materialien for e, f in m.einheiten.items()],
        )
        cur.executemany(
            "INSERT INTO erp.best_kopf (best_nr, kred_nr, datum) VALUES (%s, %s, %s)",
            [(b.best_nr, b.kred_nr, b.datum) for b in welt.bestellungen],
        )
        cur.executemany(
            "INSERT INTO erp.best_pos (best_nr, pos, mat_nr, menge, preis_netto) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (b.best_nr, p.pos, p.mat_nr, p.menge, p.preis_netto)
                for b in welt.bestellungen
                for p in b.positionen
            ],
        )
        cur.executemany(
            "INSERT INTO erp.we_pos (we_nr, best_nr, pos, menge_geliefert, datum) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(w.we_nr, w.best_nr, w.pos, w.menge_geliefert, w.datum) for w in welt.wareneingaenge],
        )
        cur.executemany(
            "INSERT INTO erp.re_hist (kred_nr, re_nr, best_nr, betrag_brutto, datum) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(h.kred_nr, h.re_nr, h.best_nr, h.betrag_brutto, h.datum) for h in welt.re_hist],
        )
        cur.executemany(
            "INSERT INTO erp.re_hist_pos (kred_nr, re_nr, best_nr, pos, menge_berechnet) "
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (h.kred_nr, h.re_nr, p.best_nr, p.pos, p.menge_berechnet)
                for h in welt.re_hist
                for p in h.positionen
            ],
        )
        cur.executemany(
            "INSERT INTO app.faelle (fall_id, pdf_pfad) VALUES (%s, %s)",
            [(f, str(eingang / f"{f}.pdf")) for f in fall_ids],
        )
