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
| Regelwerk R1–R15 (Referenz-Implementierung der Spezifikation) | ✅ |
| Datengenerator mit Gold-Labels und PDF-Rendering | ✅ |
| Eval-Harness (Kostenmatrix, gepaarter Bootstrap, Test-Split-Sperre) | ✅ |
| Baselines B0/B1, Stufe 1 (Regex-Extraktion + Regeln) | ✅ |
| Stufe 2 (LLM-Extraktion) | ✅ |
| Policy-Middleware, Audit-Log (append-only, geschwärzt) | ✅ |
| Stufe 3 (Agent mit Tools, LangGraph, `interrupt` für Freigaben über der Grenze) | ✅ |
| Angriffsfälle | ⏳ |

## Eval-Ladder

Jede Stufe ändert genau eine Sache und wird mit gepaartem Bootstrap gegen die vorherige verglichen.

| Stufe | Inhalt |
|---|---|
| B0 | Immer freigeben |
| B1 | Immer eskalieren |
| 1 | Regeln ohne LLM |
| 2 | Regeln + LLM-Extraktion |
| 3 | Agent mit Lese-Tools entscheidet statt des Regelwerks; dieselbe Policy |

Hauptmetrik sind die **Kosten pro 100 Rechnungen** über eine Kostenmatrix in Euro. Eine Freigabe, die nicht hätte erfolgen dürfen, kostet den zu viel gezahlten Betrag oder bei Betrug den ganzen Rechnungsbetrag.

**Zwei Layouts:** Dev und Smoke enthalten nur Layout A. Im Test-Split ist die Hälfte der Fälle jedes Typs in **Layout C** gerendert, einem Format, das bei der Entwicklung keiner Stufe vorkam. Ergebnisse werden getrennt nach Layout berichtet. So wird sichtbar, ob eine Stufe nur das bekannte Format beherrscht oder auch ein neues Lieferantenformat.

```bash
uv run invoice eval --stufe regeln --split dev      # beliebig oft
uv run invoice eval --stufe agent:nim_gross --split smoke  # Stufe 3 über NVIDIA NIM
uv run invoice eval --stufe regeln --split test     # genau einmal pro Stufe
uv run invoice compare runs/<lauf_a> runs/<lauf_b>  # gepaarter Bootstrap, 95-%-Intervall
```

## Schnellstart

```bash
cp .env.example .env
docker compose up -d --wait
uv sync
uv run pytest
uv run invoice generate   # 300 Rechnungen nach data/v1 (PDFs, ERP-Daten, Gold-Labels)
uv run invoice load       # ERP-Daten und Fälle in Postgres laden
```

Der Generator ist deterministisch (fester Seed, reproduzierbare PDF-Bytes). `data/v1/manifest.json` enthält den Git-Commit, die Prüfsumme der Spezifikation und der Gold-Labels.

| Pfad | Inhalt | Sichtbar für |
|---|---|---|
| `data/v1/eingang/` | Rechnungen als PDF | Agent |
| `data/v1/erp.json` | Stammdaten, Bestellungen, Wareneingänge, Rechnungshistorie | Agent (über Postgres, nur lesend) |
| `data/v1/eval/` | Gold-Labels, wahre Rechnungsdaten, Render-Varianten | nur Eval-Harness |

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

- Die Regex-Extraktion von Stufe 1 kennt Layout A vollständig. Ihr Ergebnis auf Layout A ist darum eine Obergrenze und kein fairer Vergleich. Aussagekräftig ist Layout C im Test-Split.
- Die Token-Kosten stehen auf 0 €, weil das genutzte NVIDIA-NIM-Kontingent kostenlos ist. Ein Betrieb mit bezahlter API würde die Kosten pro 100 Rechnungen für die LLM-Stufen erhöhen.
- Text für das LLM wird nicht pseudonymisiert. Die Rechnungen sind synthetisch, und die Lieferanten sind Firmen. Geschwärzt wird im Audit-Log.
