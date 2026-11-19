"""Läufe speichern und laden. Der Test-Split darf pro Stufe nur einmal ausgewertet werden."""

import json
from datetime import UTC, datetime
from pathlib import Path

from invoice_agent.eval.metriken import Metriken, Vorhersage

REGISTER = "test_register.json"


class SplitBereitsVerwendet(RuntimeError):
    pass


def _register(wurzel: Path) -> dict[str, str]:
    pfad = wurzel / REGISTER
    if not pfad.exists():
        return {}
    daten: dict[str, str] = json.loads(pfad.read_text(encoding="utf-8"))
    return daten


def pruefe_test_freigabe(wurzel: Path, stufe: str) -> None:
    """Wirft, wenn für diese Stufe schon ein Test-Lauf existiert (ADR: Test nur einmal)."""
    vorhanden = _register(wurzel).get(stufe)
    if vorhanden:
        raise SplitBereitsVerwendet(
            f"Stufe '{stufe}' wurde auf Test bereits ausgewertet (Lauf {vorhanden}). "
            f"Ein zweiter Lauf ist nur mit dokumentierter Begründung erlaubt: "
            f"Eintrag in {wurzel / REGISTER} manuell entfernen und im Bericht vermerken."
        )


def neue_lauf_id(stufe: str, split: str) -> str:
    return f"{stufe}_{split}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def speichere(
    wurzel: Path,
    stufe: str,
    split: str,
    vorhersagen: list[Vorhersage],
    metriken: Metriken,
    meta: dict[str, object],
    lauf_id: str | None = None,
) -> Path:
    if split == "test":
        pruefe_test_freigabe(wurzel, stufe)
    lauf_id = lauf_id or neue_lauf_id(stufe, split)
    zeit = lauf_id.rsplit("_", 1)[-1]
    ordner = wurzel / lauf_id
    ordner.mkdir(parents=True, exist_ok=False)
    with (ordner / "vorhersagen.jsonl").open("w", encoding="utf-8") as f:
        for v in vorhersagen:
            f.write(v.model_dump_json() + "\n")
    (ordner / "metriken.json").write_text(metriken.model_dump_json(indent=2), encoding="utf-8")
    meta_voll = {"lauf_id": lauf_id, "stufe": stufe, "split": split, "zeit": zeit, **meta}
    (ordner / "meta.json").write_text(json.dumps(meta_voll, indent=2), encoding="utf-8")
    if split == "test":
        register = _register(wurzel)
        register[stufe] = lauf_id
        (wurzel / REGISTER).write_text(json.dumps(register, indent=2), encoding="utf-8")
    return ordner


def lade_vorhersagen(ordner: Path) -> list[Vorhersage]:
    with (ordner / "vorhersagen.jsonl").open(encoding="utf-8") as f:
        return [Vorhersage.model_validate_json(z) for z in f if z.strip()]


def lade_meta(ordner: Path) -> dict[str, object]:
    daten: dict[str, object] = json.loads((ordner / "meta.json").read_text(encoding="utf-8"))
    return daten
