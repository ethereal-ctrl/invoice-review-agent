"""Eval-Ladder im Cockpit: Latenz nur aus Läufen, die überwiegend live liefen."""

import json
from pathlib import Path

from invoice_agent.ui.app import _kennzahlen  # pyright: ignore[reportPrivateUsage]


def _lauf(runs: Path, name: str, **m: object) -> None:
    ordner = runs / name
    ordner.mkdir(parents=True)
    basis = {"kosten_pro_100": "1", "latenz_p50_ms": 0.0}
    (ordner / "metriken.json").write_text(json.dumps({**basis, **m}), encoding="utf-8")


def test_latenz_aus_live_lauf(tmp_path: Path) -> None:
    _lauf(tmp_path, "agent:nim_gross_dev_20261119T100000Z", latenz_p50_ms=120_000.0)
    _lauf(
        tmp_path, "agent:nim_gross_dev_20261119T110000Z", latenz_p50_ms=98.0
    )  # alt, aus dem Cache
    _lauf(tmp_path, "agent:nim_gross_dev_20261119T120000Z", latenz_p50_ms=5.0, anteil_cache=1.0)
    _lauf(tmp_path, "regeln_dev_20261119T100000Z", latenz_p50_ms=12.0)
    zeilen = {z["stufe"]: z for z in _kennzahlen(tmp_path)}
    agent = zeilen["agent:nim_gross"]
    assert agent["lauf"] == "agent:nim_gross_dev_20261119T120000Z"  # Kosten: letzter Lauf
    assert agent["latenz_live_p50_ms"] == 120_000.0  # Latenz: letzter Live-Lauf
    assert zeilen["regeln"]["latenz_live_p50_ms"] == 12.0  # ohne LLM immer live
