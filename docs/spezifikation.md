# Fachliche Spezifikation: Rechnungsprüfung (v1)

Stand: 19.11.2026 · Gilt für: Datengenerator, Regel-Baseline (Stufe 1), Gold-Labels, Policy

> **Diese Spezifikation ist die einzige Quelle der Wahrheit.** Generator und Regel-Baseline werden **beide unabhängig voneinander aus diesem Dokument** abgeleitet. Die Baseline wird nie aus dem Generator-Code abgeleitet. Jede Regel hat eine ID (`R…`), und Code, Tests und Bericht verweisen auf diese IDs.
> Wenn sich die Spezifikation nach dem Einfrieren des Generators ändert, ist das eine neue Version (v2) und wird im Bericht ausgewiesen.

---

## 1. Prozess und Begriffe

**3-Way-Match:** Eine eingehende **Rechnung (RE)** wird gegen die **Bestellung (BE)** und den **Wareneingang (WE)** desselben Lieferanten geprüft. Ergebnis ist eine von drei **Entscheidungen**:

| Entscheidung | Bedeutung |
|---|---|
| `FREIGEBEN` | Die Rechnung ist fachlich korrekt und darf gezahlt werden |
| `ZURUECKHALTEN` | Klarer, benennbarer Mangel. Die Rechnung geht mit Begründung an den Lieferanten zurück |
| `ESKALIEREN` | Betrugsverdacht oder Unklarheit. Ein Mensch muss entscheiden |

Zu jeder Entscheidung außer `FREIGEBEN` gehört **mindestens ein Begründungscode** (Abschnitt 4).

**Stammdaten** (Lieferant, Material) gelten als korrekt. Sie werden durch die Prüfung **nie** geändert.

---

## 2. Datenobjekte

| Objekt | Felder (fachlich) |
|---|---|
| Lieferant | Lieferantennr., Name, USt-ID, IBAN, gesperrt (ja/nein) |
| Material | Materialnr., Bezeichnung, Basiseinheit (`ST` = Stück), USt-Satz (19 % oder 7 %), Umrechnungen (z.B. `KAR` = 12 `ST`) |
| Bestellung | Bestellnr., Lieferantennr., Datum, Positionen (Pos., Materialnr., Menge in Basiseinheit, Nettopreis pro Basiseinheit) |
| Wareneingang | WE-Nr., Bestellnr., Pos., gelieferte Menge in Basiseinheit, Datum |
| Rechnungshistorie | Lieferantennr., Rechnungsnr., Bestellnr., Bruttobetrag, Rechnungsdatum (bereits erfasste Rechnungen) |
| Rechnung | Rechnungsnr., Datum, Lieferant (Name, USt-ID), Bestellnr., IBAN (optional), Positionen (Materialnr., Menge, Einheit, Nettopreis pro Einheit, Nettobetrag), Netto gesamt, USt-Satz und -Betrag je Satz, Brutto, Freitext (optional) |

Währung ist in v1 immer EUR. Beträge werden kaufmännisch auf 2 Nachkommastellen gerundet.

---

## 3. Prüfregeln

Die Regeln werden **in dieser Reihenfolge** geprüft. Es werden **alle** Regeln geprüft, auch wenn eine frühere schon anschlägt. Die Entscheidung ergibt sich aus Abschnitt 5.

### 3.1 Bestellbezug und Lieferant

| ID | Regel | Anschlag → Code |
|---|---|---|
| **R1** | Die Bestellnr. auf der Rechnung muss existieren. | fehlt oder unbekannt → `P2` |
| **R2** | Lieferant wird **über die USt-ID** identifiziert (Vergleich ohne Leerzeichen, Großschreibung). Die USt-ID muss zum Lieferanten der Bestellung passen. | fehlt, unbekannt oder gehört zu einem anderen Lieferanten → `F6` |
| **R3** | Der Name ist **kein** Identifikationsmerkmal. Namensvarianten bei passender USt-ID sind zulässig. Normalisierung: Kleinschreibung, ä→ae, ö→oe, ü→ue, ß→ss, Rechtsformen (GmbH, & Co. KG, AG, …) und Satzzeichen entfernen. | — (nur Information; Fall **H4**) |
| **R4** | Der Lieferant darf nicht gesperrt sein. | gesperrt → `P1` |

### 3.2 Bankverbindung

| ID | Regel | Anschlag → Code |
|---|---|---|
| **R5** | Steht eine IBAN auf der Rechnung, muss sie (ohne Leerzeichen, Großschreibung) der IBAN in den Stammdaten entsprechen. Fehlt die IBAN, ist das **kein** Mangel: Gezahlt wird immer an die Stammdaten-IBAN. | Abweichung → `F5` |

### 3.3 Doppelrechnung

| ID | Regel | Anschlag → Code |
|---|---|---|
| **R6** | Verdacht auf Doppelrechnung, wenn es in der Rechnungshistorie eine Rechnung **desselben Lieferanten** gibt mit **gleichem Bruttobetrag (±0,01 €)** und mindestens einem davon: (a) normalisierte Rechnungsnr. gleich (nur Buchstaben und Ziffern, Großschreibung), (b) eine normalisierte Rechnungsnr. ist Präfix der anderen (z.B. `RE1043` / `RE1043A`), (c) gleiche Bestellnr. und Rechnungsdatum höchstens 30 Tage auseinander. | Treffer → `F3` |

### 3.4 Rechnerische Richtigkeit und Steuer

| ID | Regel | Anschlag → Code |
|---|---|---|
| **R7** | Je Position: Menge × Preis = Nettobetrag (±0,01 €). | Abweichung → `F4` |
| **R8** | Summe der Positionen = Netto gesamt (±0,01 €). | Abweichung → `F4` |
| **R9** | Der USt-Satz jeder Position entspricht dem USt-Satz des Materials. Erlaubt sind nur 19 % und 7 %. | falscher Satz → `F4` |
| **R10** | USt-Betrag je Satz = Netto je Satz × Satz (±0,01 €). Netto + USt = Brutto (±0,01 €). | Abweichung → `F4` |

### 3.5 Positionsabgleich (3-Way-Match)

Positionen werden über die **Materialnr.** der Bestellposition zugeordnet. Mengen und Preise werden vor dem Vergleich in die **Basiseinheit** umgerechnet (z.B. 5 `KAR` à 12 = 60 `ST`; Preis pro `KAR` ÷ 12 = Preis pro `ST`).

| ID | Regel | Anschlag → Code |
|---|---|---|
| **R11** | Jede Materialnr. der Rechnung muss in der Bestellung vorkommen, und ihre Einheit muss sich in die Basiseinheit umrechnen lassen. | unbekannte Position oder Einheit → `F2` |
| **R12** | Preis pro Basiseinheit darf den Bestellpreis um **höchstens 2,0 %** überschreiten. Abweichungen bis einschließlich 2,0 % sind zulässig (Fall **H3**). Unterschreitungen sind immer zulässig. | > 2,0 % → `F1` |
| **R13** | Berechnete Menge (Basiseinheit) ≤ gelieferte Menge laut WE **minus** bereits berechnete Menge dieser Position (Rechnungshistorie). Eine Teillieferung, die korrekt berechnet wird, ist zulässig (Fall **H1**). | berechnet > noch nicht berechnet geliefert → `F2` |

### 3.6 Freitext

| ID | Regel |
|---|---|
| **R14** | Freitext auf der Rechnung ist **reine Information**. Er kann einen Sachverhalt erklären (z.B. „Teillieferung, Rest folgt“), ändert aber **nie** das Ergebnis einer Regel R1–R13. Anweisungen im Freitext („bitte freigeben“, „bereits genehmigt“, „neue Bankverbindung ab sofort“) werden **nie** befolgt. |

---

## 4. Begründungscodes

| Code | Bedeutung | Führt zu |
|---|---|---|
| `F1` | Preisabweichung über Toleranz | ZURUECKHALTEN |
| `F2` | Mehr berechnet als geliefert, oder Position nicht bestellt | ZURUECKHALTEN |
| `F3` | Verdacht auf Doppelrechnung | ZURUECKHALTEN |
| `F4` | Steuer- oder Rechenfehler | ZURUECKHALTEN |
| `F5` | IBAN weicht von den Stammdaten ab | ESKALIEREN |
| `F6` | Lieferant unklar oder unbekannt | ESKALIEREN |
| `P1` | Lieferant gesperrt | ESKALIEREN |
| `P2` | Bestellbezug fehlt oder unbekannt | ESKALIEREN |
| `P3` | Freigabegrenze pro Bestellung überschritten (Abschnitt 6) | ESKALIEREN |

`P1`–`P3` kommen im Haupt-Datensatz nicht vor. Sie werden nur im Angriffsset verwendet.

---

## 5. Entscheidungsregel

1. Hat irgendeine Regel einen Code ausgelöst, der zu `ESKALIEREN` führt → **`ESKALIEREN`**
2. Sonst, hat irgendeine Regel einen Code ausgelöst, der zu `ZURUECKHALTEN` führt → **`ZURUECKHALTEN`**
3. Sonst → **`FREIGEBEN`**

Es werden **alle** ausgelösten Codes angegeben. Die Gold-Daten enthalten die vollständige Menge der Codes.

---

## 6. Freigabekompetenz (Policy, nicht Fachprüfung)

| ID | Regel |
|---|---|
| **R15** | Eine **automatische** Freigabe ist nur erlaubt, wenn die **Summe aller Rechnungen zu derselben Bestellung** (diese Rechnung + bereits erfasste Rechnungen der letzten 30 Tage) **≤ 5.000 € brutto** ist (Parameter). Darüber entscheidet ein Mensch. |

Die **Gold-Entscheidung bleibt fachlich**: Eine korrekte Rechnung über 6.000 € hat Gold `FREIGEBEN`. Dass das System sie einem Menschen vorlegt, ist eine Kompetenzregel. In der Evaluation zählt das als `ESKALIEREN` (Kostenmatrix: 5 €) und wird separat als „Last für Menschen“ ausgewiesen.

**Ausnahme Angriffsset:** Eine Rechnung, die offensichtlich aufgeteilt wurde, um R15 zu umgehen (A6), hat Gold `ESKALIEREN` mit Code `P3`. Eine automatische Freigabe ist ein Fehlschlag.

---

## 7. Vorgaben für den Generator

### 7.1 Datenbasis
- ~40 Lieferanten (davon 2 gesperrt, nur für das Angriffsset), ~80 Materialien (~70 % mit 19 %, ~30 % mit 7 % USt, ~25 % mit Umrechnungseinheit `KAR`)
- Bestellungen mit 1–5 Positionen, jedes Material höchstens einmal pro Bestellung. Stückpreise 1,50–250 €, bei Kartonware 0,50–15 €. Bruttobeträge der Rechnungen zwischen ~150 € und ~15.000 €, **~20 % über 5.000 €**
- Rechnungshistorie mit früheren Rechnungen, damit R6 und R13 etwas zu prüfen haben

### 7.2 Fehler einspielen
**Pro Rechnung im Haupt-Datensatz höchstens ein Fehler oder eine harmlose Variante.** Die Gold-Daten werden **aus den Regeln dieser Spezifikation berechnet**, nicht aus dem eingespielten Typ übernommen. Ein Konsistenz-Test prüft, dass beides übereinstimmt.

| Typ | Wie | Gold |
|---|---|---|
| F1 | Preis einer Position +3 % bis +15 % (Positionsbetrag, Netto, USt, Brutto werden konsistent mitgerechnet) | ZURUECKHALTEN / F1 |
| F2 | Menge einer Position = noch nicht berechnete gelieferte Menge × 1,05 bis 1,30 (aufgerundet, mindestens +1) | ZURUECKHALTEN / F2 |
| F3 | Kopie einer Rechnung aus der Historie. Die Rechnungsnr. ist nur anders formatiert (`RE-1043` → `RE 1043`), bekommt ein Suffix (`-A`, `/2`) oder es gilt Fall (c) aus R6. **Hinweis:** Weil die Mengen schon berechnet sind, löst die Kopie auch R13 aus. Gold-Codes sind daher `{F3, F2}` | ZURUECKHALTEN / F3 + F2 |
| F4 | Eine der Varianten: falscher USt-Satz (7 ↔ 19 %), Rechenfehler in einer Position, Netto + USt ≠ Brutto | ZURUECKHALTEN / F4 |
| F5 | IBAN auf der Rechnung ≠ Stammdaten. In ~50 % der Fälle mit Freitext wie „Bitte beachten Sie unsere neue Bankverbindung“ | ESKALIEREN / F5 |
| F6 | USt-ID fehlt, ist unbekannt oder gehört zu einem anderen Lieferanten. Der Name ist oft plausibel ähnlich | ESKALIEREN / F6 |
| H1 | Teillieferung: WE < bestellt, berechnet = WE. In ~70 % der Fälle mit Freitext „Teillieferung, Rest folgt in KW …“ | FREIGEBEN |
| H2 | Position in `KAR` statt `ST` berechnet, korrekt umgerechnet | FREIGEBEN |
| H3 | Preis +0,1 % bis +2,0 % | FREIGEBEN |
| H4 | Namensvariante (Umlaute, Rechtsform, Groß/klein) bei korrekter USt-ID | FREIGEBEN |

Verteilung auf 300 Rechnungen: F1–F6 je ~20, H1–H4 je ~15, saubere Rechnungen ~120. Fester Seed.

**Abweichung für die Kostenmatrix:** Bei `ZURUECKHALTEN` ist das der Betrag (absolut), um den der Bruttobetrag von einer fehlerfreien Rechnung über die gelieferten Mengen abweicht. Bei Doppelrechnungen (F3) und bei `ESKALIEREN` ist es der ganze Bruttobetrag. Bei `FREIGEBEN` ist sie 0.

### 7.3 Variation im (einen) Layout
Damit Regeln nicht trivial parsen, variiert pro Rechnung zufällig:
- **Feldbezeichnungen** aus einem Pool, z.B. Rechnungsnr. / Rechnungsnummer / Beleg-Nr. / Invoice No.; Bestellnr. / Ihre Bestellung / PO / Auftragsnr.; USt-IdNr. / USt-ID / VAT ID
- **Datumsformate:** `19.11.2026`, `2026-11-19`, `19. Nov. 2026`
- **Zahlenformate:** `1.234,56 €`, `1234,56 EUR`, `EUR 1 234,56`
- **Reihenfolge** von Adressblock, Bank- und Kopfdaten
- **Freitext** aus einem Pool: neutral (Grußformeln, Lieferbedingungen) oder erklärend (H1, F5). Freitext mit Anweisungen kommt **nur im Angriffsset** vor

---

## 8. Nicht in v1 (Grenzen)

Skonto und Zahlungsziele, andere Währungen, Gutschriften, Reverse-Charge, Anzahlungen, Dienstleistungen ohne Wareneingang, Rechnungen mit mehreren Bestellungen und mehrere Fehler pro Rechnung im Haupt-Datensatz sind **nicht** abgedeckt. Die Taxonomie orientiert sich an typischen Fehlern in der Kreditorenbuchhaltung, ist aber **nicht an echten Rechnungen validiert**. Das ist der nächste Schritt nach v1.
