# 0003: LangGraph für den Agenten

- **Status:** angenommen
- **Datum:** 2026-11-19

## Kontext

Stufe 3 ist ein Agent, der mit Lese-Tools auf das ERP prüft und mit einer Aktion abschließt. Er braucht: eine Schleife aus LLM-Aufruf und Tool-Ausführung, ein Schrittlimit, einen Halt für Freigaben durch einen Menschen (Kompetenzgrenze R15), der später an derselben Stelle weiterläuft, und nachvollziehbare Zustände. Die Policy-Middleware (ADR 0005) muss vor jeder Tool-Ausführung sitzen.

## Entscheidung

Der Agent ist ein `StateGraph` aus LangGraph mit vier Knoten (`src/invoice_agent/stufen/agent.py`):

```
extrahieren -> agent <-> werkzeuge -> (mensch) -> Ende
```

- `werkzeuge` schickt jeden Tool-Aufruf als Antrag an die Policy und führt nur Erlaubtes aus.
- `mensch` ruft `interrupt()` auf. Der Graph hält mit Checkpoint an und läuft mit `Command(resume={"freigeben": True|False})` weiter.
- Das LLM wird **nicht** über LangChain-Modellklassen angebunden, sondern über den eigenen Client (Cache, Replay, Rate Limiter). LangGraph orchestriert nur. So bleibt die CI im Replay-Modus deterministisch (ADR 0007).
- Natives Tool Calling (OpenAI-Format), am 19.11.2026 mit Gemma 4 31B auf NVIDIA NIM geprüft.

## Alternativen

- **Eigene Schleife ohne Framework:** wenige Zeilen, aber `interrupt` mit Fortsetzen, Checkpoints und ein Graph, den man zeigen kann, müssten nachgebaut werden. In Projekt 1 war eine eigene Pipeline richtig, weil es dort keinen Zustand über Schritte gab.
- **CrewAI / AutoGen:** auf Rollen und Gespräche mehrerer Agenten ausgelegt. Hier gibt es einen Agenten mit festem Ablauf. Menschliche Freigabe mitten im Ablauf ist in LangGraph ein eingebautes Konzept.
- **LangChain-Agent mit `ChatOpenAI`:** verworfen, weil dann Cache und Replay am eigenen Client vorbeilaufen.

## Konsequenzen

- Der Checkpointer ist im Eval-Lauf `InMemorySaver`. Für einen echten Betrieb, in dem ein Mensch Stunden später freigibt, braucht es einen persistenten Checkpointer (Postgres). Das ist nicht umgesetzt.
- Der Graph ist mit einem Fake-LLM vollständig testbar (`tests/test_agent.py`): Freigabe, Ablehnung durch die Policy, unbekanntes Tool, fremder Fall, interrupt mit Fortsetzen, Schrittlimit.
- Falsch wäre die Entscheidung, wenn LangGraph-Updates den Graphen häufiger brechen, als die eingebauten Konzepte Arbeit sparen.
