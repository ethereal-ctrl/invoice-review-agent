"""Regelwerk R1-R13 und R15 der Spezifikation auf strukturierten Daten.

Dieses Modul ist die Referenz-Implementierung der Spezifikation. Es wird genutzt,
um Gold-Labels aus den wahren Rechnungsdaten zu berechnen, und von Stufe 1 und 2
auf den jeweils extrahierten Daten. Es importiert keinen Generator-Code.
R14 (Freitext ändert nichts) ist dadurch erfüllt, dass der Freitext nirgends gelesen wird.
"""

from collections import defaultdict
from decimal import Decimal

from invoice_agent import normalize
from invoice_agent.config import PolicyConfig, Toleranzen
from invoice_agent.domain import Code
from invoice_agent.model import Bestellung, Lieferant, Material, Rechnung, ReHist, Welt

ERLAUBTE_SAETZE = frozenset({Decimal("7"), Decimal("19")})


class Index:
    """Nachschlagetabellen über die Welt (nur lesend)."""

    def __init__(self, welt: Welt) -> None:
        self.lieferant: dict[str, Lieferant] = {lf.kred_nr: lf for lf in welt.lieferanten}
        self.lieferant_nach_ust: dict[str, Lieferant] = {
            normalize.ust_id(lf.ust_id): lf for lf in welt.lieferanten
        }
        self.material: dict[str, Material] = {m.mat_nr: m for m in welt.materialien}
        self.bestellung: dict[str, Bestellung] = {b.best_nr: b for b in welt.bestellungen}

        self.geliefert: defaultdict[tuple[str, int], int] = defaultdict(int)
        for we in welt.wareneingaenge:
            self.geliefert[(we.best_nr, we.pos)] += we.menge_geliefert

        self.berechnet: defaultdict[tuple[str, int], int] = defaultdict(int)
        self.historie: defaultdict[str, list[ReHist]] = defaultdict(list)
        for h in welt.re_hist:
            self.historie[h.kred_nr].append(h)
            for p in h.positionen:
                self.berechnet[(p.best_nr, p.pos)] += p.menge_berechnet


def _gleich(a: Decimal, b: Decimal, tol: Toleranzen) -> bool:
    return abs(a - b) <= tol.betrag_eur


def pruefe(re: Rechnung, idx: Index, tol: Toleranzen) -> frozenset[Code]:
    """Alle Regeln prüfen und die Menge der ausgelösten Codes liefern (Abschnitt 3)."""
    codes: set[Code] = set()

    # R1: Bestellbezug
    bestellung = idx.bestellung.get(re.best_nr) if re.best_nr else None
    if bestellung is None:
        codes.add(Code.P2)

    # R2: Identifikation über die USt-ID (R3: der Name spielt keine Rolle)
    nach_ust = idx.lieferant_nach_ust.get(normalize.ust_id(re.ust_id)) if re.ust_id else None
    if nach_ust is None or (bestellung is not None and nach_ust.kred_nr != bestellung.kred_nr):
        codes.add(Code.F6)

    lieferant = idx.lieferant[bestellung.kred_nr] if bestellung is not None else nach_ust
    if lieferant is not None:
        # R4: gesperrt
        if lieferant.gesperrt:
            codes.add(Code.P1)
        # R5: IBAN (fehlende IBAN ist kein Mangel)
        if re.iban and normalize.iban(re.iban) != normalize.iban(lieferant.iban):
            codes.add(Code.F5)
        # R6: Doppelrechnung
        if _ist_doppelrechnung(re, lieferant, idx, tol):
            codes.add(Code.F3)

    codes |= _rechnerisch(re, idx, tol)
    if bestellung is not None:
        codes |= _abgleich(re, bestellung, idx, tol)
    return frozenset(codes)


def _ist_doppelrechnung(re: Rechnung, lieferant: Lieferant, idx: Index, tol: Toleranzen) -> bool:
    neu = normalize.rechnungsnr(re.re_nr)
    for h in idx.historie[lieferant.kred_nr]:
        if not _gleich(h.betrag_brutto, re.brutto, tol):
            continue
        alt = normalize.rechnungsnr(h.re_nr)
        if neu and alt and (neu == alt or neu.startswith(alt) or alt.startswith(neu)):
            return True
        tage = abs((re.datum - h.datum).days)
        if re.best_nr == h.best_nr and tage <= tol.duplikat_tage:
            return True
    return False


def _rechnerisch(re: Rechnung, idx: Index, tol: Toleranzen) -> set[Code]:
    """R7-R10: Positionen, Summen, Steuersätze, Steuerbeträge."""
    fehler = False
    netto_je_satz: defaultdict[Decimal, Decimal] = defaultdict(Decimal)

    for p in re.positionen:
        if not _gleich(p.menge * p.preis_netto, p.betrag_netto, tol):  # R7
            fehler = True
        material = idx.material.get(p.mat_nr)
        if p.ust_satz not in ERLAUBTE_SAETZE or (  # R9
            material is not None and p.ust_satz != material.ust_satz
        ):
            fehler = True
        netto_je_satz[p.ust_satz] += p.betrag_netto

    if not _gleich(sum((p.betrag_netto for p in re.positionen), Decimal(0)), re.netto, tol):  # R8
        fehler = True

    # R10: je Satz Netto und Steuer, insgesamt Netto + USt = Brutto
    zeilen = {z.satz: z for z in re.ust}
    if set(zeilen) != set(netto_je_satz):
        fehler = True
    for satz, zeile in zeilen.items():
        if not _gleich(zeile.netto, netto_je_satz.get(satz, Decimal(0)), tol):
            fehler = True
        if not _gleich(zeile.netto * satz / 100, zeile.betrag, tol):
            fehler = True
    ust_summe = sum((z.betrag for z in re.ust), Decimal(0))
    if not _gleich(re.netto + ust_summe, re.brutto, tol):
        fehler = True

    return {Code.F4} if fehler else set()


def _abgleich(re: Rechnung, bestellung: Bestellung, idx: Index, tol: Toleranzen) -> set[Code]:
    """R11-R13: 3-Way-Match in der Basiseinheit."""
    codes: set[Code] = set()
    nach_material = {p.mat_nr: p for p in bestellung.positionen}
    berechnet_jetzt: defaultdict[int, int] = defaultdict(int)
    grenze = 1 + tol.preis_prozent / 100

    for p in re.positionen:
        bp = nach_material.get(p.mat_nr)
        material = idx.material.get(p.mat_nr)
        faktor = material.faktor(p.einheit) if material is not None else None
        if bp is None or faktor is None:  # R11 (auch: Einheit ohne Umrechnung)
            codes.add(Code.F2)
            continue
        if p.preis_netto / faktor > bp.preis_netto * grenze:  # R12
            codes.add(Code.F1)
        berechnet_jetzt[bp.pos] += p.menge * faktor

    for pos, menge in berechnet_jetzt.items():  # R13
        schluessel = (bestellung.best_nr, pos)
        offen = idx.geliefert[schluessel] - idx.berechnet[schluessel]
        if menge > offen:
            codes.add(Code.F2)
    return codes


def kumuliert_brutto(re: Rechnung, idx: Index, policy: PolicyConfig) -> Decimal:
    """R15: Summe dieser Rechnung und der erfassten Rechnungen zur selben Bestellung."""
    summe = re.brutto
    if re.best_nr is None:
        return summe
    for rechnungen in idx.historie.values():
        for h in rechnungen:
            tage = (re.datum - h.datum).days
            if h.best_nr == re.best_nr and 0 <= tage <= policy.fenster_tage:
                summe += h.betrag_brutto
    return summe
