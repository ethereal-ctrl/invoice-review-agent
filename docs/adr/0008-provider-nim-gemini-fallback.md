# 0008: Provider NVIDIA NIM, Gemini als Fallback, nie gemischt

- **Status:** angenommen (Fallback bisher ungetestet)
- **Datum:** 2026-11-19

## Kontext

Das Budget ist 0 €. Gebraucht wird ein großes Modell mit Tool Calling für Stufe 2 und 3, das Hunderte Rechnungen mit mehreren Aufrufen pro Rechnung schafft. Lokale Modelle auf einem MacBook mit 16 GB sind dafür zu langsam: Qwen 3.5 4B brauchte 93–212 s pro Extraktion und scheiterte bei einem Fall am Schema.

## Entscheidung

- **Gemma 4 31B über NVIDIA NIM** (kostenloses Kontingent, OpenAI-kompatibel, natives Tool Calling, am 19.11.2026 geprüft). Große Läufe laufen nachts, wenn die Latenz niedriger ist.
- **Gemini API als Fallback** mit demselben Modell, aber **nie innerhalb eines Laufs gemischt**. Ein Lauf hat genau ein Profil, das im Lauf-Ordner (`meta.json`) steht. Der Cache ist pro Provider getrennt.
- Profile stehen in `configs/default.yaml` (Rate Limit, Timeout, notionelle Preise).

## Alternativen

- **Bezahlte API:** außerhalb des Budgets. Die notionellen Preise lassen sich aber eintragen, um die Token-Kosten pro 100 Rechnungen zu zeigen.
- **Lokales Modell:** nur als Vergleich auf kleinen Mengen sinnvoll.
- **Provider pro Anfrage wechseln (Load Balancing):** verworfen, weil die Ergebnisse dann nicht mehr einem Modell zuzuordnen wären.

## Konsequenzen

- Die Token-Kosten stehen auf 0 €. Das ist im README unter „Grenzen“ genannt.
- Tagsüber dauern einzelne Aufrufe bis zu 2 Minuten (p50 im ersten Smoke-Lauf von Stufe 3: 174 s pro Rechnung). Das Timeout steht auf 300 s, und abgebrochene Fälle werden fail-safe eskaliert und beim Wiederholen aus dem Cache ergänzt.
- Der Gemini-Fallback ist ohne API-Key nicht getestet, und die Modell-ID dort ist nicht geprüft. Vor dem Test-Lauf nachholen oder als Grenze nennen.
