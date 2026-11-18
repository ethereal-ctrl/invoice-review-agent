"""Gold-Label eines Falls. Wird vom Generator geschrieben und nur vom Eval-Harness gelesen."""

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from invoice_agent.domain import Code, Entscheidung


class Gold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fall_id: str
    split: str  # "dev" | "test"
    smoke: bool
    typ: str
    variante: str | None
    entscheidung: Entscheidung
    codes: tuple[Code, ...]
    brutto: Decimal
    abweichung_eur: Decimal  # Betrag, der bei falscher Freigabe zu viel gezahlt würde
    layout: str = "A"  # "C" nur im Test-Split (unbekanntes Lieferantenformat)


def lade_gold(pfad: Path) -> list[Gold]:
    with pfad.open(encoding="utf-8") as f:
        return [Gold.model_validate_json(zeile) for zeile in f if zeile.strip()]
