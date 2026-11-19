"""Entscheidung eines Menschen über einen Fall, den die Policy vorgelegt hat (R15).

Alles in einer Transaktion: Freigabe sperren (`FOR UPDATE`, damit zwei Sachbearbeiter nicht
gleichzeitig entscheiden), Ergebnis eintragen, Entscheidung speichern, Fall schließen und
das Protokoll ergänzen. Hat ein Agent den Fall vorgelegt, wird sein LangGraph-Thread mit
`Command(resume=...)` fortgesetzt, sodass der Graph sauber endet.
"""

from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from invoice_agent.audit import Ereignis
from invoice_agent.domain import Entscheidung


class FreigabeFehler(RuntimeError):
    pass


Fortsetzen = Callable[[str, str, bool], None]  # (stufe, thread_id, freigeben)


def offene(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(
            """
            SELECT fall_id, run_id, stufe, vorschlag, policy_regel, brutto, grund_codes, erstellt
            FROM app.freigaben WHERE ergebnis IS NULL ORDER BY erstellt, fall_id
            """
        ).fetchall()


def entscheide(
    conn: psycopg.Connection,
    fall_id: str,
    freigeben: bool,
    von: str,
    fortsetzen: Fortsetzen | None = None,
) -> Entscheidung:
    von = von.strip()
    if not von:
        raise FreigabeFehler("Name der entscheidenden Person fehlt")
    ergebnis = Entscheidung.FREIGEBEN if freigeben else Entscheidung.ZURUECKHALTEN
    with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        f = cur.execute(
            "SELECT * FROM app.freigaben WHERE fall_id = %s AND ergebnis IS NULL FOR UPDATE",
            (fall_id,),
        ).fetchone()
        if f is None:
            raise FreigabeFehler(f"{fall_id} wartet nicht (mehr) auf eine Entscheidung")
        if f["thread_id"] and fortsetzen is not None:
            fortsetzen(f["stufe"], f["thread_id"], freigeben)
        cur.execute(
            "UPDATE app.freigaben SET ergebnis = %s, entschieden_von = %s, entschieden_am = now()"
            " WHERE fall_id = %s",
            (ergebnis.value, von, fall_id),
        )
        cur.execute(
            """
            INSERT INTO app.entscheidungen (fall_id, run_id, stufe, entscheidung, grund_codes)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (fall_id, f["run_id"], f"mensch({f['stufe']})", ergebnis.value, f["grund_codes"]),
        )
        cur.execute("UPDATE app.faelle SET status = 'erledigt' WHERE fall_id = %s", (fall_id,))
        e = Ereignis(
            run_id=f["run_id"],
            fall_id=fall_id,
            knoten="mensch",
            tool="freigeben",
            args_geschwaerzt={"von": von, "vorschlag": f["vorschlag"]},
            policy_regel=f["policy_regel"],
            ergebnis=ergebnis.value,
        )
        cur.execute(
            """
            INSERT INTO audit.ereignisse
                (ts, run_id, fall_id, knoten, tool, args_geschwaerzt, policy_regel, ergebnis)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                e.ts, e.run_id, e.fall_id, e.knoten, e.tool,
                Jsonb(e.args_geschwaerzt), e.policy_regel, e.ergebnis,
            ),
        )  # fmt: skip
    return ergebnis
