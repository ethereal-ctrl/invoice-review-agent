"""Ergebnis des Generators auf die Platte schreiben.

Aufteilung nach Sichtbarkeit:
- `eingang/`  PDFs, die der Agent sieht
- `erp.json`  Stammdaten und Belege, die in die Datenbank geladen werden
- `eval/`     Gold-Labels und wahre Rechnungsdaten, nur für das Eval-Harness
"""

import hashlib
import json
import random
import subprocess
from pathlib import Path

from invoice_agent.config import Settings
from invoice_agent.generator.faelle import TYPEN, VERTEILUNG, Ergebnis
from invoice_agent.generator.render import render, waehle_variante

GENERATOR_VERSION = "v1"


def _sha256(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _git_stand() -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout
        return {"commit": commit, "unsauber": bool(status.strip())}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "unsauber": None}


def schreibe(
    ergebnis: Ergebnis, settings: Settings, ziel: Path, spezifikation: Path
) -> dict[str, object]:
    eingang, eval_dir = ziel / "eingang", ziel / "eval"
    eingang.mkdir(parents=True, exist_ok=True)
    eval_dir.mkdir(parents=True, exist_ok=True)

    (ziel / "erp.json").write_text(ergebnis.welt.model_dump_json(indent=1), encoding="utf-8")

    seed = settings.generator.seed
    with (
        (eval_dir / "gold.jsonl").open("w", encoding="utf-8") as gold,
        (eval_dir / "rechnungen.jsonl").open("w", encoding="utf-8") as rechnungen,
        (eval_dir / "varianten.jsonl").open("w", encoding="utf-8") as varianten,
    ):
        for fall in ergebnis.faelle:
            variante = waehle_variante(
                random.Random(f"{seed}:render:{fall.fall_id}"), fall.gold.layout
            )
            render(fall.rechnung, eingang / f"{fall.fall_id}.pdf", variante)
            gold.write(fall.gold.model_dump_json() + "\n")
            rechnungen.write(
                json.dumps({"fall_id": fall.fall_id, **fall.rechnung.model_dump(mode="json")})
                + "\n"
            )
            varianten.write(
                json.dumps({"fall_id": fall.fall_id, **variante.als_dict()}, ensure_ascii=False)
                + "\n"
            )

    faelle = ergebnis.faelle
    manifest: dict[str, object] = {
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "anzahl": len(faelle),
        "verteilung": {t: VERTEILUNG[t] for t in TYPEN},
        "splits": {
            "dev": sum(f.gold.split == "dev" for f in faelle),
            "test": sum(f.gold.split == "test" for f in faelle),
            "smoke": sum(f.gold.smoke for f in faelle),
        },
        "verworfene_versuche": ergebnis.verworfen,
        "spezifikation_sha256": _sha256(spezifikation),
        "gold_sha256": _sha256(eval_dir / "gold.jsonl"),
        "git": _git_stand(),
    }
    (ziel / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
