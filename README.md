# invoice-agent

**Ein Agent für Rechnungsprüfung (3-Way-Match), der genauso streng gemessen wird wie ein Forschungsexperiment.**

> _Business-Aussage folgt nach dem Test-Lauf. Hier stehen dann nur gemessene Zahlen: Kosten pro 100 Rechnungen, unsichere Freigaben, Last für Menschen._

Eingehende Rechnungen werden gegen Bestellung, Wareneingang und Stammdaten geprüft. Ergebnis ist eine von drei Entscheidungen: **FREIGEBEN**, **ZURÜCKHALTEN** (mit Begründungscode) oder **ESKALIEREN** an einen Menschen. Eine Policy-Schicht um jeden Tool-Aufruf sorgt dafür, dass das LLM keine Regel umgehen kann.

## Status

| Baustein | Stand |
|---|---|
| Fachliche Spezifikation | ✅ [docs/spezifikation.md](docs/spezifikation.md) |
| Domänenmodell, Normalisierung, Config | ✅ |
| Postgres-Schema mit getrennten Rollen | ✅ |
| Datengenerator mit Gold-Labels | ⏳ |
| Eval-Harness, Baselines, Stufe 1 (Regeln) | ⏳ |
| Stufe 2 (LLM-Extraktion) | ⏳ |
| Policy-Middleware, Audit-Log | ⏳ |
| Stufe 3 (Agent mit Tools, LangGraph) | ⏳ |
| Angriffsfälle | ⏳ |

## Eval-Ladder

Jede Stufe ändert genau eine Sache und wird mit gepaartem Bootstrap gegen die vorherige verglichen.

| Stufe | Inhalt |
|---|---|
| B0 | Immer freigeben |
| B1 | Immer eskalieren |
| 1 | Regeln ohne LLM |
| 2 | Regeln + LLM-Extraktion |
| 3 | Agent mit Tools |

Hauptmetrik sind die **Kosten pro 100 Rechnungen** über eine Kostenmatrix in Euro. Eine Freigabe, die nicht hätte erfolgen dürfen, kostet den zu viel gezahlten Betrag oder bei Betrug den ganzen Rechnungsbetrag.

## Schnellstart

```bash
cp .env.example .env
docker compose up -d --wait
uv sync
uv run pytest
```

## Entwicklung

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not db"   # ohne Datenbank
```

## Aufbau

```
src/invoice_agent/   Code (Domänenmodell, Normalisierung, Config, CLI)
configs/             YAML-Konfiguration (Toleranzen, Policy, Generator)
db/init/             Schema und Rollen (erp, app, audit)
docs/                Spezifikation und ADRs
tests/               pytest
```

## Architekturentscheidungen

Siehe [docs/adr](docs/adr/README.md).

## Grenzen

Synthetische Daten, ein PDF-Layout, nur EUR, kein Skonto. Die Taxonomie orientiert sich an typischen Fehlern in der Kreditorenbuchhaltung und ist nicht an echten Rechnungen validiert. Details in [docs/spezifikation.md](docs/spezifikation.md), Abschnitt 8.
