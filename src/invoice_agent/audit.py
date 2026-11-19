"""Audit-Log: Jeder Antrag an die Policy wird protokolliert, Argumente geschwärzt.

Drei Senken mit derselben Schnittstelle:
- `SpeicherAudit` für Tests,
- `JsonlAudit` für Eval-Läufe (eine Datei pro Lauf),
- `PostgresAudit` für den Betrieb: schreibt als Rolle `ia_agent` in `audit.ereignisse`,
  die nur INSERT darf. Deshalb kein `RETURNING`: das bräuchte SELECT.
"""

import json
import re
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

_IBAN = re.compile(r"\b([A-Z]{2})\d{2}(?:\s?[A-Z0-9]){10,30}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.-]+)\b")


def _schwaerze_text(text: str) -> str:
    def iban(m: re.Match[str]) -> str:
        kompakt = m.group(0).replace(" ", "")
        return f"{m.group(1)}**…{kompakt[-4:]}"

    return _EMAIL.sub(r"***@\1", _IBAN.sub(iban, text))


def schwaerze(wert: object) -> object:
    """IBANs bis auf Land und letzte 4 Stellen, E-Mail-Adressen bis auf die Domain."""
    if isinstance(wert, str):
        return _schwaerze_text(wert)
    if isinstance(wert, Mapping):
        return {str(k): schwaerze(v) for k, v in cast(Mapping[object, object], wert).items()}
    if isinstance(wert, list | tuple):
        return [schwaerze(v) for v in cast(list[object], wert)]
    if wert is None or isinstance(wert, bool | int | float):
        return wert
    return _schwaerze_text(str(wert))


class Ereignis(BaseModel):
    """Eine Zeile in `audit.ereignisse`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    fall_id: str | None
    knoten: str
    tool: str | None = None
    args_geschwaerzt: object = None
    policy_regel: str | None = None
    ergebnis: str
    modell: str | None = None
    tokens_ein: int | None = None
    tokens_aus: int | None = None


class Audit(Protocol):
    def schreibe(self, ereignis: Ereignis) -> None: ...


class SpeicherAudit:
    def __init__(self) -> None:
        self.ereignisse: list[Ereignis] = []
        self._lock = threading.Lock()

    def schreibe(self, ereignis: Ereignis) -> None:
        with self._lock:
            self.ereignisse.append(ereignis)


class JsonlAudit:
    """Hängt an eine Datei an; mehrere Worker-Threads teilen sich eine Instanz."""

    def __init__(self, pfad: Path) -> None:
        self.pfad = pfad
        self._lock = threading.Lock()
        pfad.parent.mkdir(parents=True, exist_ok=True)

    def schreibe(self, ereignis: Ereignis) -> None:
        zeile = ereignis.model_dump_json() + "\n"
        with self._lock, self.pfad.open("a", encoding="utf-8") as f:
            f.write(zeile)


class PostgresAudit:
    """Schreibt in `audit.ereignisse`. Jede Zeile wird sofort committet."""

    def __init__(self, dsn: str) -> None:
        self._conn = psycopg.connect(dsn, autocommit=True)
        self._lock = threading.Lock()

    def schreibe(self, ereignis: Ereignis) -> None:
        e = ereignis
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO audit.ereignisse
                    (ts, run_id, fall_id, knoten, tool, args_geschwaerzt,
                     policy_regel, ergebnis, modell, tokens_ein, tokens_aus)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    e.ts,
                    e.run_id,
                    e.fall_id,
                    e.knoten,
                    e.tool,
                    None if e.args_geschwaerzt is None else Jsonb(e.args_geschwaerzt),
                    e.policy_regel,
                    e.ergebnis,
                    e.modell,
                    e.tokens_ein,
                    e.tokens_aus,
                ),
            )

    def schliesse(self) -> None:
        self._conn.close()


def lade_jsonl(pfad: Path) -> list[Ereignis]:
    with pfad.open(encoding="utf-8") as f:
        return [Ereignis.model_validate(json.loads(z)) for z in f if z.strip()]
