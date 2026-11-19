"""Lesezugriff auf das ERP für die Tools des Agenten (Stufe 3).

Zwei Umsetzungen mit identischen Antworten:
- `WeltErp` liest aus der geladenen Welt im Speicher (Eval-Läufe, CI ohne Datenbank),
- `PostgresErp` liest als Rolle `ia_agent` (nur SELECT auf `erp`) mit parametrisierten
  Queries. SQL in einem Feld wie der Bestellnummer ist damit nur ein Suchwert (Angriff A9).

Alle Antworten sind JSON-fähig: Beträge als Text, Mengen in der Basiseinheit.
"""

import threading
from collections import defaultdict
from decimal import Decimal
from typing import Any, LiteralString, Protocol, cast

import psycopg

from invoice_agent import normalize
from invoice_agent.model import Welt
from invoice_agent.pruefung import Index

Json = dict[str, object]


def _preis(d: Decimal) -> str:
    return f"{d:.4f}"


def _betrag(d: Decimal) -> str:
    return f"{d:.2f}"


def _satz(d: Decimal) -> str:
    return f"{d.normalize():f}"


class Erp(Protocol):
    def bestellung(self, best_nr: str) -> Json | None: ...
    def wareneingang(self, best_nr: str) -> list[Json]: ...
    def lieferant(
        self, *, ust_id: str | None = None, kred_nr: str | None = None
    ) -> Json | None: ...
    def rechnungshistorie(self, kred_nr: str) -> list[Json]: ...


class WeltErp:
    def __init__(self, welt: Welt) -> None:
        self._idx = Index(welt)
        self._we: defaultdict[str, dict[int, int]] = defaultdict(dict)
        for (best_nr, pos), menge in self._idx.geliefert.items():
            self._we[best_nr][pos] = menge

    def bestellung(self, best_nr: str) -> Json | None:
        b = self._idx.bestellung.get(best_nr)
        if b is None:
            return None
        positionen: list[Json] = []
        for p in b.positionen:
            m = self._idx.material[p.mat_nr]
            positionen.append(
                {
                    "pos": p.pos,
                    "mat_nr": p.mat_nr,
                    "bezeichnung": m.bezeichnung,
                    "menge": p.menge,
                    "basis_einheit": m.basis_einheit,
                    "preis_netto_pro_basiseinheit": _preis(p.preis_netto),
                    "ust_satz": _satz(m.ust_satz),
                    "einheiten": dict(sorted(m.einheiten.items())),
                }
            )
        return {
            "best_nr": b.best_nr,
            "kred_nr": b.kred_nr,
            "datum": b.datum.isoformat(),
            "positionen": positionen,
        }

    def wareneingang(self, best_nr: str) -> list[Json]:
        b = self._idx.bestellung.get(best_nr)
        if b is None:
            return []
        return [
            {
                "pos": p.pos,
                "geliefert": self._idx.geliefert.get((best_nr, p.pos), 0),
                "bereits_berechnet": self._idx.berechnet.get((best_nr, p.pos), 0),
            }
            for p in b.positionen
        ]

    def lieferant(self, *, ust_id: str | None = None, kred_nr: str | None = None) -> Json | None:
        if ust_id is not None:
            lf = self._idx.lieferant_nach_ust.get(normalize.ust_id(ust_id))
        elif kred_nr is not None:
            lf = self._idx.lieferant.get(kred_nr)
        else:
            return None
        if lf is None:
            return None
        return {
            "kred_nr": lf.kred_nr,
            "name": lf.name,
            "ust_id": lf.ust_id,
            "iban": lf.iban,
            "gesperrt": lf.gesperrt,
        }

    def rechnungshistorie(self, kred_nr: str) -> list[Json]:
        hist = sorted(self._idx.historie.get(kred_nr, []), key=lambda h: (h.datum, h.re_nr))
        return [
            {
                "re_nr": h.re_nr,
                "best_nr": h.best_nr,
                "datum": h.datum.isoformat(),
                "betrag_brutto": _betrag(h.betrag_brutto),
            }
            for h in hist
        ]


class PostgresErp:
    """Eine Verbindung, durch einen Lock geschützt; die Abfragen sind kurz."""

    def __init__(self, dsn: str) -> None:
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._lock = threading.Lock()

    def _alle(self, sql: str, params: tuple[object, ...]) -> list[dict[str, Any]]:
        # Nur feste SQL-Texte aus diesem Modul; Werte gehen immer als Parameter.
        with self._lock:
            cur = self._conn.execute(cast(LiteralString, sql), params)
            namen = [d.name for d in cur.description or []]
            return [dict(zip(namen, zeile, strict=True)) for zeile in cur.fetchall()]

    def bestellung(self, best_nr: str) -> Json | None:
        kopf = self._alle(
            "SELECT best_nr, kred_nr, datum FROM erp.best_kopf WHERE best_nr = %s", (best_nr,)
        )
        if not kopf:
            return None
        pos = self._alle(
            """
            SELECT p.pos, p.mat_nr, m.bezeichnung, p.menge, m.basis_einheit, p.preis_netto,
                   m.ust_satz,
                   coalesce((SELECT jsonb_object_agg(e.einheit, e.faktor ORDER BY e.einheit)
                             FROM erp.mat_einh e WHERE e.mat_nr = p.mat_nr), '{}') AS einheiten
            FROM erp.best_pos p JOIN erp.mat_stamm m USING (mat_nr)
            WHERE p.best_nr = %s ORDER BY p.pos
            """,
            (best_nr,),
        )
        k = kopf[0]
        return {
            "best_nr": k["best_nr"],
            "kred_nr": k["kred_nr"],
            "datum": k["datum"].isoformat(),
            "positionen": [
                {
                    "pos": r["pos"],
                    "mat_nr": r["mat_nr"],
                    "bezeichnung": r["bezeichnung"],
                    "menge": r["menge"],
                    "basis_einheit": r["basis_einheit"],
                    "preis_netto_pro_basiseinheit": _preis(r["preis_netto"]),
                    "ust_satz": _satz(r["ust_satz"]),
                    "einheiten": r["einheiten"],
                }
                for r in pos
            ],
        }

    def wareneingang(self, best_nr: str) -> list[Json]:
        return self._alle(
            """
            SELECT p.pos,
                   coalesce((SELECT sum(w.menge_geliefert) FROM erp.we_pos w
                             WHERE w.best_nr = p.best_nr AND w.pos = p.pos), 0)::int
                       AS geliefert,
                   coalesce((SELECT sum(h.menge_berechnet) FROM erp.re_hist_pos h
                             WHERE h.best_nr = p.best_nr AND h.pos = p.pos), 0)::int
                       AS bereits_berechnet
            FROM erp.best_pos p WHERE p.best_nr = %s ORDER BY p.pos
            """,
            (best_nr,),
        )

    def lieferant(self, *, ust_id: str | None = None, kred_nr: str | None = None) -> Json | None:
        felder = "SELECT kred_nr, name, ust_id, iban, gesperrt FROM erp.kred_stamm"
        if ust_id is not None:
            zeilen = self._alle(
                f"{felder} WHERE upper(regexp_replace(ust_id, '\\s', '', 'g')) = %s",
                (normalize.ust_id(ust_id),),
            )
        elif kred_nr is not None:
            zeilen = self._alle(f"{felder} WHERE kred_nr = %s", (kred_nr,))
        else:
            return None
        return zeilen[0] if zeilen else None

    def rechnungshistorie(self, kred_nr: str) -> list[Json]:
        zeilen = self._alle(
            """
            SELECT re_nr, best_nr, datum, betrag_brutto FROM erp.re_hist
            WHERE kred_nr = %s ORDER BY datum, re_nr
            """,
            (kred_nr,),
        )
        return [
            {
                "re_nr": z["re_nr"],
                "best_nr": z["best_nr"],
                "datum": z["datum"].isoformat(),
                "betrag_brutto": _betrag(z["betrag_brutto"]),
            }
            for z in zeilen
        ]

    def schliesse(self) -> None:
        self._conn.close()
