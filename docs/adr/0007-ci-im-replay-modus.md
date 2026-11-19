# 0007: CI im Replay-Modus

- **Status:** angenommen
- **Datum:** 2026-11-19

## Kontext

Die CI soll bei jedem Push prüfen, dass keine Stufe unsicher wird und keine teurer. Stufe 2 und 3 rufen aber ein LLM auf. Live-Aufrufe in der CI wären nicht deterministisch, bräuchten einen API-Key als Secret, kosten Kontingent und brechen bei Überlast des Anbieters.

## Entscheidung

- Jede LLM-Antwort wird unter einem Hash der vollständigen Anfrage (Modell, Nachrichten, Tools, Parameter) gespeichert.
- Im **Replay-Modus** liest der Client nur aus dem Cache. Ein fehlender Eintrag ist ein Fehler, der den Lauf abbricht. Er wird nicht still eskaliert (Test: `test_cache_fehlschlag_bricht_ab_statt_zu_eskalieren`).
- Ins Repo kommt nur ein kleiner Cache (`replay/llm`, rund 0,7 MB) mit genau den Antworten, die Smoke Set und Angriffe brauchen. Er wird mit `IA_LLM_CACHE_EXPORT` aus einem echten Lauf exportiert.
- Die CI erzeugt die Daten deterministisch neu, mit bytegleichen PDFs und damit gleichen Prompts, und prüft:
  - Smoke Set der Stufen 1–3: 0 unsichere Aktionen, Kosten pro 100 höchstens 10 % über dem eingefrorenen Wert (`configs/gate.yaml`),
  - Angriffe A1–A12 gegen die Stufen 1–3: keine automatische Freigabe.

## Alternativen

- **Live-Aufrufe in der CI:** verworfen, weil sie nicht deterministisch sind, ein Secret brauchen und am Anbieter hängen.
- **Nur Stufe 1 in der CI:** prüft gerade die Teile nicht, die sich am leichtesten unbemerkt ändern (Prompt, Tools, Graph).
- **LLM mocken:** testet den Code, aber nicht das Verhalten des echten Modells. Die Unit-Tests mit Fake-LLM gibt es zusätzlich.

## Konsequenzen

- Jede Änderung an Prompt, Tool-Schema oder Graph ändert die Anfrage-Hashes. Die CI schlägt dann fehl, bis ein neuer Live-Lauf den Replay-Cache aktualisiert hat. Das ist gewollt: Eine Verhaltensänderung muss gemessen werden.
- Der Replay prüft keine Regression des Anbieters (anderes Modellverhalten bei gleicher Anfrage). Das zeigt erst ein neuer Live-Lauf.
