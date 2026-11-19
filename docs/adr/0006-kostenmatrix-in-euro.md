# 0006: Kostenmatrix in Euro und Umrechnung auf 5 % Fehlerquote

- **Status:** angenommen
- **Datum:** 2026-11-19

## Kontext

Genauigkeit allein ist für Rechnungsprüfung irreführend. Eine fälschlich freigegebene Betrugsrechnung über 8.000 € und eine unnötig eskalierte Rechnung zählen gleich viel, kosten aber ganz verschieden viel. Außerdem enthält der Datensatz absichtlich 40 % fehlerhafte Rechnungen, in der Praxis sind es eher wenige Prozent.

## Entscheidung

Hauptmetrik sind die **Kosten pro 100 Rechnungen** in Euro, mit dieser Matrix (Zeile: Gold, Spalte: effektive Entscheidung; ein `interrupt` zählt als ESKALIEREN):

| Gold \ System | Freigeben | Zurückhalten | Eskalieren |
|---|---|---|---|
| Freigeben | 0 | 15 € | 5 € |
| Zurückhalten | zu viel gezahlter Betrag | 0 | 5 € |
| Eskalieren | ganzer Rechnungsbetrag | 10 € | 0 |

- **15 €:** Nacharbeit, verlorenes Skonto, Ärger beim Lieferanten.
- **5 €:** etwa fünf Minuten Sachbearbeitung.
- **10 €:** gestoppt, aber falsch begründet. Der Fall muss trotzdem noch untersucht werden.
- Unsichere Aktionen (Freigabe, obwohl Gold nicht Freigeben ist) werden zusätzlich als eigene Rate berichtet und sind im Gate hart auf 0 gesetzt (`configs/gate.yaml`).
- Für eine realistische Aussage werden die Kosten zusätzlich auf eine **Fehlerquote von 5 %** umgerechnet (Gewichtung der fehlerhaften und der fehlerfreien Fälle).
- Unterschiede zwischen Stufen werden mit gepaartem Bootstrap (2.000 Wiederholungen, 95-%-Intervall) geprüft.

## Alternativen

- **Genauigkeit oder F1:** ignoriert, dass Fehler verschieden teuer sind.
- **Nur die Rate unsicherer Aktionen:** belohnt eine Stufe, die alles eskaliert (B1). Die Kosten der Last für Menschen fehlen dann.

## Konsequenzen

- Die Pauschalen sind Annahmen. Sie stehen in der Config, und die Sensitivität (Faktor 0,5 und 2) wird im Bericht gezeigt.
- Weil Fehlfreigaben den ganzen Rechnungsbetrag kosten, dominieren sie die Kosten. B0 (immer freigeben) liegt bei rund 74.000 € pro 100, B1 (immer eskalieren) bei 440 €.
- Falsch wäre die Entscheidung, wenn die Reihenfolge der Stufen von den Pauschalen abhängt. Genau das prüft die Sensitivitätsanalyse.
