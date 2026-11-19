# 0002: Use Case Rechnungsprüfung mit 3-Way-Match

- **Status:** angenommen
- **Datum:** 2026-11-19

## Kontext

Das Projekt soll zeigen, wie ein Agent einen Geschäftsprozess automatisiert und dabei kontrollierbar bleibt. Der Use Case braucht drei Eigenschaften: eine fachlich eindeutige richtige Antwort (sonst ist nichts messbar), echtes Geld als Risiko (sonst ist Governance Dekoration) und Daten aus mehreren Systemen (sonst braucht es keine Tools).

## Entscheidung

Eingangsrechnungen werden gegen Bestellung, Wareneingang und Stammdaten geprüft (3-Way-Match). Es gibt drei Ergebnisse: FREIGEBEN, ZURÜCKHALTEN (Fehler, den der Lieferant korrigiert) und ESKALIEREN (Betrugsverdacht, Lieferant oder Bestellung unklar). Die Regeln stehen in einer fachlichen Spezifikation (R1–R15), bevor es Code gibt (ADR 0001).

## Alternativen

- **Allgemeiner Chat-Assistent über Dokumente:** Es gibt keine eindeutig richtige Antwort, deshalb ist nur ein LLM-Judge möglich. Das hat Projekt 1 schon abgedeckt.
- **Modernisierung von Legacy-Code (COBOL, Java):** passt zu IBM Z und zu Capgeminis Value Pool 1, aber die Korrektheit lässt sich in drei Tagen nicht belastbar messen.
- **Bestellanforderungen oder Reisekosten:** ähnlich, aber mit weniger klaren Betrugsmustern (IBAN-Wechsel, Doppelrechnung, Aufteilen unter die Grenze).

## Konsequenzen

- Die Kosten einer falschen Entscheidung lassen sich in Euro ausdrücken (ADR 0006). Damit wird „produktionsreif“ zu einer Zahl statt zu einer Behauptung.
- Rechnungsprüfung gilt als Standard-Beispiel. Abheben muss sich das Projekt deshalb über die Messung und die Kontrollen, nicht über den Use Case selbst.
- Falsch wäre die Entscheidung, wenn sich die Regeln in der Praxis nicht vollständig spezifizieren lassen. Genau das ist aber auch die Grenze, an der ein Agent mehr bringen könnte als ein Regelwerk. Siehe die Ergebnisse von Stufe 3.
