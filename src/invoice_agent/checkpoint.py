"""Persistenter LangGraph-Checkpointer in Postgres (Schema `lg`).

Damit kann ein anderer Prozess (das Freigabe-Cockpit als Rolle `ia_mensch`) einen Agenten
fortsetzen, der Stunden vorher im Worker an der Kompetenzgrenze angehalten hat.
Die Tabellen legt der Worker (Rolle `ia_agent`, darf in `lg` anlegen) mit `setup()` an.
"""

from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver  # pyright: ignore[reportMissingTypeStubs]
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def postgres_checkpointer(dsn: str, anlegen: bool = False) -> tuple[Any, ConnectionPool]:
    pool: ConnectionPool = ConnectionPool(
        dsn,
        min_size=1,
        max_size=8,
        open=True,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": "-c search_path=lg",
        },
    )
    saver = PostgresSaver(pool)  # pyright: ignore[reportArgumentType]
    if anlegen:
        saver.setup()
    return saver, pool
