"""Eine Stufe auf einem Split laufen lassen und das Ergebnis speichern."""

import json
from pathlib import Path

from invoice_agent.config import Settings
from invoice_agent.eval import laeufe
from invoice_agent.eval.metriken import Metriken, berechne
from invoice_agent.gold import Gold, lade_gold
from invoice_agent.model import Welt
from invoice_agent.stufen.baselines import ImmerEskalieren, ImmerFreigeben
from invoice_agent.stufen.basis import Stufe
from invoice_agent.stufen.regeln import regeln

STUFEN = ("b0", "b1", "regeln")
SPLITS = ("dev", "test", "smoke")


def baue_stufe(name: str, settings: Settings, welt: Welt) -> Stufe:
    if name == "b0":
        return ImmerFreigeben()
    if name == "b1":
        return ImmerEskalieren()
    if name == "regeln":
        return regeln(settings, welt)
    raise ValueError(f"Unbekannte Stufe {name!r}, bekannt: {', '.join(STUFEN)}")


def auswahl(gold: list[Gold], split: str) -> list[Gold]:
    if split == "smoke":
        return [g for g in gold if g.smoke]
    if split in ("dev", "test"):
        return [g for g in gold if g.split == split]
    raise ValueError(f"Unbekannter Split {split!r}")


def lauf(
    stufe_name: str, split: str, settings: Settings, daten: Path, wurzel: Path
) -> tuple[Path, Metriken]:
    if split == "test":
        laeufe.pruefe_test_freigabe(wurzel, stufe_name)  # vor der Arbeit, nicht danach
    gold = auswahl(lade_gold(daten / "eval" / "gold.jsonl"), split)
    welt = Welt.model_validate_json((daten / "erp.json").read_text(encoding="utf-8"))
    stufe = baue_stufe(stufe_name, settings, welt)
    vorhersagen = [
        stufe.entscheide(g.fall_id, daten / "eingang" / f"{g.fall_id}.pdf") for g in gold
    ]
    metriken = berechne(gold, vorhersagen, settings.kosten)
    manifest = json.loads((daten / "manifest.json").read_text(encoding="utf-8"))
    meta: dict[str, object] = {
        "daten": str(daten),
        "gold_sha256": manifest["gold_sha256"],
        "generator_commit": manifest["git"]["commit"],
    }
    ordner = laeufe.speichere(wurzel, stufe_name, split, vorhersagen, metriken, meta)
    return ordner, metriken
