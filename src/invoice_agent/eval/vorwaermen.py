"""Cache vorwärmen, bevor der Test-Split einmal ausgewertet wird.

Der Test-Split darf pro Stufe nur einmal gespeichert werden. Bricht unterwegs die Verbindung
ab, wären betroffene Fälle fail-safe eskaliert und das Ergebnis verfälscht. Deshalb:

1. `waerme`: Stufe live über alle Fälle laufen lassen. Fälle mit Infrastrukturfehlern
   (Netz, Timeout, 5xx) werden wiederholt, bis alle beantwortet sind. Gespeichert werden
   nur Latenzen und Fehlerzahlen, **keine Entscheidungen, keine Metriken, kein Gold**.
2. Danach `invoice eval --split test --replay`: Alles kommt aus dem Cache. Fehlt ein Eintrag,
   bricht der Lauf vor dem Speichern ab (`CacheFehlschlag`), und das Register bleibt frei.

Die Latenz des Test-Laufs stammt aus der Vorwärm-Datei, denn der Replay-Lauf misst nur den Cache.
"""

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from invoice_agent.eval.metriken import Vorhersage
from invoice_agent.stufen.basis import Stufe


def ist_infrastrukturfehler(v: Vorhersage) -> bool:
    """Fehlschlag durch Netz oder Anbieter, nicht durch das Modell (dann wiederholbar)."""
    regel = v.policy_regel or ""
    return regel.startswith("llm_fehler") or "LLM nicht erreichbar" in (v.fehler or "")


@dataclass
class Bericht:
    anzahl: int
    offen: list[str]  # nach allen Versuchen noch mit Infrastrukturfehler
    latenzen_live_ms: list[float]
    durchgaenge: int

    @property
    def vollstaendig(self) -> bool:
        return not self.offen


def waerme(
    stufe: Stufe,
    faelle: list[tuple[str, Path]],
    worker: int,
    versuche: int = 3,
    pause_s: float = 120.0,
    meldung: Callable[[str], None] = print,
) -> Bericht:
    def eins(fall: tuple[str, Path]) -> Vorhersage:
        return stufe.entscheide(fall[0], fall[1])

    offen = list(faelle)
    latenzen: list[float] = []
    durchgaenge = 0
    for durchgang in range(1, versuche + 1):
        durchgaenge = durchgang
        with ThreadPoolExecutor(max_workers=worker) as pool:
            ergebnisse = list(pool.map(eins, offen))
        latenzen += [v.latenz_ms for v in ergebnisse if not v.aus_cache]
        fehlgeschlagen = {v.fall_id for v in ergebnisse if ist_infrastrukturfehler(v)}
        meldung(
            f"Durchgang {durchgang}: {len(offen)} Fälle, {len(fehlgeschlagen)} Infrastrukturfehler"
        )
        offen = [f for f in offen if f[0] in fehlgeschlagen]
        if not offen:
            break
        if durchgang < versuche:
            time.sleep(pause_s)
    return Bericht(len(faelle), [f for f, _ in offen], latenzen, durchgaenge)


def speichere_bericht(wurzel: Path, stufe: str, split: str, b: Bericht) -> Path:
    ordner = wurzel / "vorwaermen"
    ordner.mkdir(parents=True, exist_ok=True)
    zeit = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    pfad = ordner / f"{stufe}_{split}_{zeit}.json"
    s = sorted(b.latenzen_live_ms)

    def p(q: float) -> float | None:
        return s[min(len(s) - 1, round(q * (len(s) - 1)))] if s else None

    pfad.write_text(
        json.dumps(
            {
                "stufe": stufe,
                "split": split,
                "anzahl": b.anzahl,
                "durchgaenge": b.durchgaenge,
                "offen": b.offen,
                "live_faelle": len(s),
                "latenz_p50_ms": p(0.5),
                "latenz_p95_ms": p(0.95),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return pfad
