"""Postgres als Queue (ADR 0004) und der Worker, der sie abarbeitet.

Ein Fall wird mit `FOR UPDATE SKIP LOCKED` geholt: Mehrere Worker greifen nie denselben Fall,
und keiner wartet auf eine Sperre eines anderen. Entscheidung und Statuswechsel landen in
**einer** Transaktion. Stürzt ein Worker ab, bleibt der Fall `in_arbeit` und wird nach einer
Frist wieder freigegeben (`gib_haengende_frei`), bis die Höchstzahl an Versuchen erreicht ist.

Der Worker läuft als Rolle `ia_agent`: ERP nur lesen, Queue lesen und schreiben, Audit nur
einfügen. Die Welt für die Policy liest er zu Beginn aus der Datenbank, nicht aus Dateien.
"""

import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from invoice_agent.eval.metriken import Vorhersage
from invoice_agent.model import (
    Bestellung,
    BestPos,
    Lieferant,
    Material,
    ReHist,
    ReHistPos,
    Welt,
    WePos,
)
from invoice_agent.stufen.basis import Stufe

MAX_VERSUCHE = 3

_HOLEN = """
UPDATE app.faelle SET status = 'in_arbeit', locked_at = now(), versuche = versuche + 1
WHERE fall_id = (
    SELECT fall_id FROM app.faelle
    WHERE status = 'offen'
    ORDER BY erstellt, fall_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING fall_id, pdf_pfad
"""


def hole_fall(conn: psycopg.Connection) -> tuple[str, Path] | None:
    with conn.transaction():
        zeile = conn.execute(_HOLEN).fetchone()
    return None if zeile is None else (str(zeile[0]), Path(str(zeile[1])))


def erledige(conn: psycopg.Connection, run_id: str, stufe: str, v: Vorhersage) -> None:
    """Effektive Entscheidung speichern: Ein `interrupt` wird als ESKALIEREN eingetragen."""
    with conn.transaction():
        conn.execute(
            """
            INSERT INTO app.entscheidungen
                (fall_id, run_id, stufe, entscheidung, grund_codes, tokens_ein, tokens_aus)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                v.fall_id,
                run_id,
                stufe,
                v.effektiv.value,
                [c.value for c in v.codes],
                v.tokens_ein,
                v.tokens_aus,
            ),
        )
        conn.execute(
            "UPDATE app.faelle SET status = 'erledigt', locked_at = NULL WHERE fall_id = %s",
            (v.fall_id,),
        )


def melde_fehler(conn: psycopg.Connection, fall_id: str) -> None:
    """Zurück in die Queue, solange Versuche übrig sind; sonst `fehler`."""
    with conn.transaction():
        conn.execute(
            """
            UPDATE app.faelle
            SET status = CASE WHEN versuche >= %s THEN 'fehler' ELSE 'offen' END,
                locked_at = NULL
            WHERE fall_id = %s
            """,
            (MAX_VERSUCHE, fall_id),
        )


def gib_haengende_frei(conn: psycopg.Connection, minuten: int) -> int:
    """Fälle, die länger als `minuten` in Arbeit sind (abgestürzter Worker), wieder öffnen."""
    with conn.transaction():
        cur = conn.execute(
            """
            UPDATE app.faelle
            SET status = CASE WHEN versuche >= %s THEN 'fehler' ELSE 'offen' END,
                locked_at = NULL
            WHERE status = 'in_arbeit' AND locked_at < now() - make_interval(mins => %s)
            """,
            (MAX_VERSUCHE, minuten),
        )
        return cur.rowcount


def lies_welt(conn: psycopg.Connection) -> Welt:
    """ERP-Stand aus der Datenbank (Adressen stehen nicht im Kreditorenstamm)."""
    lieferanten = tuple(
        Lieferant(kred_nr=k, name=n, strasse="", ort="", ust_id=u, iban=i, gesperrt=g)
        for k, n, u, i, g in conn.execute(
            "SELECT kred_nr, name, ust_id, iban, gesperrt FROM erp.kred_stamm ORDER BY kred_nr"
        )
    )
    einheiten: defaultdict[str, dict[str, int]] = defaultdict(dict)
    for mat_nr, einheit, faktor in conn.execute("SELECT mat_nr, einheit, faktor FROM erp.mat_einh"):
        einheiten[mat_nr][einheit] = faktor
    materialien = tuple(
        Material(mat_nr=m, bezeichnung=b, basis_einheit=e, ust_satz=s, einheiten=einheiten[m])
        for m, b, e, s in conn.execute(
            "SELECT mat_nr, bezeichnung, basis_einheit, ust_satz FROM erp.mat_stamm ORDER BY mat_nr"
        )
    )
    positionen: defaultdict[str, list[BestPos]] = defaultdict(list)
    for best_nr, pos, mat_nr, menge, preis in conn.execute(
        "SELECT best_nr, pos, mat_nr, menge, preis_netto FROM erp.best_pos ORDER BY best_nr, pos"
    ):
        positionen[best_nr].append(BestPos(pos=pos, mat_nr=mat_nr, menge=menge, preis_netto=preis))
    bestellungen = tuple(
        Bestellung(best_nr=b, kred_nr=k, datum=d, positionen=tuple(positionen[b]))
        for b, k, d in conn.execute(
            "SELECT best_nr, kred_nr, datum FROM erp.best_kopf ORDER BY best_nr"
        )
    )
    wareneingaenge = tuple(
        WePos(we_nr=w, best_nr=b, pos=p, menge_geliefert=m, datum=d)
        for w, b, p, m, d in conn.execute(
            "SELECT we_nr, best_nr, pos, menge_geliefert, datum FROM erp.we_pos "
            "ORDER BY we_nr, best_nr, pos"
        )
    )
    hist_pos: defaultdict[tuple[str, str], list[ReHistPos]] = defaultdict(list)
    for k, r, b, p, m in conn.execute(
        "SELECT kred_nr, re_nr, best_nr, pos, menge_berechnet FROM erp.re_hist_pos "
        "ORDER BY kred_nr, re_nr, best_nr, pos"
    ):
        hist_pos[(k, r)].append(ReHistPos(best_nr=b, pos=p, menge_berechnet=m))
    re_hist = tuple(
        ReHist(
            kred_nr=k,
            re_nr=r,
            best_nr=b,
            betrag_brutto=betrag,
            datum=d,
            positionen=tuple(hist_pos[(k, r)]),
        )
        for k, r, b, betrag, d in conn.execute(
            "SELECT kred_nr, re_nr, best_nr, betrag_brutto, datum FROM erp.re_hist "
            "ORDER BY kred_nr, re_nr"
        )
    )
    return Welt(
        lieferanten=lieferanten,
        materialien=materialien,
        bestellungen=bestellungen,
        wareneingaenge=wareneingaenge,
        re_hist=re_hist,
    )


@dataclass
class Bilanz:
    erledigt: list[str] = field(default_factory=list[str])
    fehler: list[str] = field(default_factory=list[str])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def merke(self, fall_id: str, ok: bool) -> None:
        with self._lock:
            (self.erledigt if ok else self.fehler).append(fall_id)


def arbeite(
    dsn: str,
    stufe: Stufe,
    run_id: str,
    threads: int = 4,
    maximal: int | None = None,
    nach_fall: Callable[[Vorhersage], None] | None = None,
) -> Bilanz:
    """Mehrere Worker-Threads, jeder mit eigener Verbindung, bis die Queue leer ist."""
    bilanz = Bilanz()
    zaehler = threading.Semaphore(maximal) if maximal is not None else None

    def worker() -> None:
        with psycopg.connect(dsn) as conn:
            while True:
                if zaehler is not None and not zaehler.acquire(blocking=False):
                    return
                fall = hole_fall(conn)
                if fall is None:
                    return
                fall_id, pdf = fall
                try:
                    v = stufe.entscheide(fall_id, pdf)
                    erledige(conn, run_id, stufe.name, v)
                except Exception:  # Fall nicht verlieren: zurück in die Queue
                    melde_fehler(conn, fall_id)
                    bilanz.merke(fall_id, ok=False)
                    continue
                bilanz.merke(fall_id, ok=True)
                if nach_fall:
                    nach_fall(v)

    laeufer = [threading.Thread(target=worker, name=f"worker-{i}") for i in range(threads)]
    for t in laeufer:
        t.start()
    for t in laeufer:
        t.join()
    return bilanz
