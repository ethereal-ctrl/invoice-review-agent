# 0008: Provider NVIDIA NIM, Gemini als Fallback, nie gemischt

- **Status:** angenommen (Fallback am 20.11.2026 auf dem Smoke Set geprüft)
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
- **Gemini-Fallback, geprüft am 20.11.2026** auf dem Smoke Set (Modell `models/gemma-4-31b-it`):
  - Über die Gemini-API liefert Gemma immer einen Denkblock (`<thought>`), der sich bei diesem Modell nicht abschalten lässt. Er wird vor dem Parsen entfernt und nicht an den Agenten zurückgegeben. Die Denk-Tokens zählen gegen `max_tokens`. Mit 2.048 brach das JSON ab, deshalb steht das Limit im Profil auf 8.192.
  - **Stufe 2:** Alle 20 beantworteten Fälle wurden genau wie bei NIM entschieden, mit denselben Codes. 10 Fälle scheiterten an Überlastung (HTTP 503, auch nach Backoff) und wurden fail-safe eskaliert.
  - **Stufe 3:** 15 von 30 Fällen scheiterten an Überlastung. Bei den übrigen 15 weicht der Agent in 3 Entscheidungen von NIM ab (2 davon richtiger, 1 falscher), trotz Temperatur 0. Unsichere Aktionen gab es keine. In einem Fall verweigerte die Policy eine Freigabe, weil die USt-ID anders gelesen wurde (`vorbedingung:F6`).
  - Folgerung: Der Fallback funktioniert, aber das Verhalten des Agenten ist zwischen Anbietern nicht identisch, auch nicht bei gleichem Modell. Das bestätigt die Regel, Anbieter innerhalb eines Laufs nie zu mischen. Zur Zeit der Prüfung war Gemini für dieses Modell stark überlastet.
