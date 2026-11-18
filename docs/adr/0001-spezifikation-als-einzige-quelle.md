# 0001: Fachliche Spezifikation als einzige Quelle der Wahrheit

- **Status:** angenommen
- **Datum:** 2026-11-19

## Kontext

Daten, Gold-Labels und die Regel-Baseline entstehen im selben Projekt. Würde die Baseline aus dem Generator-Code abgeleitet, wüsste sie genau, welche Fehler eingespielt wurden. Die Evaluation wäre dann zirkulär und hätte keine Aussagekraft.

## Entscheidung

1. Vor dem Generator wird eine fachliche Spezifikation geschrieben ([docs/spezifikation.md](../spezifikation.md)). Jede Regel hat eine ID (R1–R15).
2. Generator und Regel-Baseline werden **unabhängig voneinander** aus der Spezifikation abgeleitet. Die Baseline importiert keinen Generator-Code.
3. Gold-Labels werden **aus den Regeln berechnet**, nicht vom eingespielten Fehlertyp übernommen. Ein Konsistenz-Test prüft, dass beides übereinstimmt.
4. Der Generator wird vor der Arbeit an Stufe 2 eingefroren. Der Commit-Hash steht im Bericht. Spätere Änderungen an der Spezifikation sind eine neue Version.

Gemeinsam genutzt werden nur Definitionen, die die Spezifikation wörtlich vorgibt: Entscheidungen, Codes, Entscheidungsregel und Normalisierungen (`domain.py`, `normalize.py`) sowie das Regelwerk R1–R15 (`pruefung.py`). Das Regelwerk arbeitet auf strukturierten Rechnungsdaten. Für die Gold-Labels bekommt es die wahren Daten, in Stufe 1 und 2 die jeweils aus dem PDF extrahierten. Der Unterschied zwischen den Stufen liegt damit allein in der Extraktion, und die Regeln kennen den Mechanismus nicht, mit dem der Generator Fehler einspielt.

Der Generator zieht Fälle per Verwerfungs-Sampling: Ein Kandidat wird nur übernommen, wenn das Regelwerk genau die für seinen Typ erwarteten Codes liefert. Nach dem letzten Fall wird die gesamte Welt noch einmal geprüft. Die Zahl verworfener Versuche steht im Manifest.

## Alternativen

- **Gold-Labels direkt vom Generator übernehmen:** einfacher, aber Widersprüche zwischen eingespieltem Fehler und Regeln (z.B. eine Doppelrechnung, die auch R13 auslöst) blieben unentdeckt.
- **Echte Rechnungen:** wären aussagekräftiger, stehen ohne Kunden aber nicht zur Verfügung.

## Konsequenzen

- Die Spezifikation muss vor dem Code fertig sein und ist danach schwer zu ändern.
- Die verbleibende Schwäche (synthetische Daten aus eigener Hand) wird nicht beseitigt, sondern offen im Abschnitt „Grenzen“ benannt.
