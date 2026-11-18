"""PDF-Rendering in einem Layout mit Variation (Spezifikation 7.3).

Pro Rechnung werden Feldbezeichnungen, Datums- und Zahlenformate, Titel und die Lage von
Bank- und Steuerangaben zufällig gewählt. Die Wahl wird zurückgegeben, damit sich Fehler
später nach Variante auswerten lassen.
"""

import random
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from invoice_agent.model import Rechnung

KUNDE = (
    "Nordwerk Handels GmbH",
    "Einkauf / Kreditorenbuchhaltung",
    "Hafenstraße 12",
    "20457 Hamburg",
)

LABELS: dict[str, tuple[str, ...]] = {
    "titel": ("Rechnung", "RECHNUNG", "Rechnung / Invoice"),
    "re_nr": ("Rechnungsnr.", "Rechnungsnummer", "Beleg-Nr.", "Invoice No."),
    "datum": ("Rechnungsdatum", "Datum", "Belegdatum", "Invoice Date"),
    "best_nr": ("Bestellnr.", "Ihre Bestellung", "PO", "Auftragsnr."),
    "ust_id": ("USt-IdNr.", "USt-ID", "VAT ID"),
    "iban": ("IBAN", "Bankverbindung IBAN", "Konto (IBAN)"),
    "netto": ("Nettobetrag", "Summe netto", "Zwischensumme", "Net total"),
    "ust": ("USt", "MwSt", "Umsatzsteuer", "VAT"),
    "brutto": ("Gesamtbetrag", "Rechnungsbetrag", "Summe brutto", "Total"),
    "menge": ("Menge", "Anzahl", "Qty"),
    "preis": ("Einzelpreis", "Preis/Einh.", "Unit price"),
    "betrag": ("Betrag", "Gesamt", "Amount"),
    "artikel": ("Artikel-Nr.", "Art.-Nr.", "Item"),
}
_MONATE = (
    "Jan.",
    "Feb.",
    "März",
    "Apr.",
    "Mai",
    "Juni",
    "Juli",
    "Aug.",
    "Sep.",
    "Okt.",
    "Nov.",
    "Dez.",
)
DATUMSFORMATE = ("dmy_punkt", "iso", "lang")
ZAHLENFORMATE = ("de_euro", "de_eur", "eur_leer")


@dataclass(frozen=True)
class Variante:
    labels: dict[str, str]
    datumsformat: str
    zahlenformat: str
    satzformat: str  # "19 %" oder "19%"
    kopf_reihenfolge: tuple[str, ...]
    bank_im_kopf: bool
    ust_id_im_kopf: bool

    def als_dict(self) -> dict[str, object]:
        return asdict(self)


def waehle_variante(rng: random.Random) -> Variante:
    kopf = ["re_nr", "datum", "best_nr"]
    rng.shuffle(kopf)
    return Variante(
        labels={k: rng.choice(v) for k, v in LABELS.items()},
        datumsformat=rng.choice(DATUMSFORMATE),
        zahlenformat=rng.choice(ZAHLENFORMATE),
        satzformat=rng.choice(("{s} %", "{s}%")),
        kopf_reihenfolge=tuple(kopf),
        bank_im_kopf=rng.random() < 0.5,
        ust_id_im_kopf=rng.random() < 0.5,
    )


def datum_text(d: date, art: str) -> str:
    if art == "iso":
        return d.isoformat()
    if art == "lang":
        return f"{d.day}. {_MONATE[d.month - 1]} {d.year}"
    return d.strftime("%d.%m.%Y")


def betrag_text(x: Decimal, art: str) -> str:
    vorzeichen = "-" if x < 0 else ""
    ganz, nachkomma = f"{abs(x):.2f}".split(".")
    if art == "de_eur":
        return f"{vorzeichen}{ganz},{nachkomma} EUR"
    gruppen = f"{int(ganz):,}"
    if art == "eur_leer":
        return f"EUR {vorzeichen}{gruppen.replace(',', ' ')},{nachkomma}"
    return f"{vorzeichen}{gruppen.replace(',', '.')},{nachkomma} €"


def satz_text(satz: Decimal, fmt: str) -> str:
    return fmt.format(s=f"{satz.normalize():f}")


def render(re: Rechnung, pfad: Path, v: Variante) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(pfad), pagesize=A4, invariant=True)  # reproduzierbare Bytes
    breite, hoehe = A4
    links, rechts = 50.0, breite - 50.0
    lb = v.labels

    # Absender
    y = hoehe - 60
    c.setFont("Helvetica-Bold", 13)
    c.drawString(links, y, re.lieferant_name)
    c.setFont("Helvetica", 9)
    c.drawString(links, y - 14, f"{re.lieferant_strasse} · {re.lieferant_ort}")

    # Empfänger
    y = hoehe - 140
    c.setFont("Helvetica", 10)
    for i, zeile in enumerate(KUNDE):
        c.drawString(links, y - i * 13, zeile)

    # Kopfdaten rechts
    werte = {
        "re_nr": re.re_nr,
        "datum": datum_text(re.datum, v.datumsformat),
        "best_nr": re.best_nr or "",
    }
    kopf: list[tuple[str, str]] = [(lb[k], werte[k]) for k in v.kopf_reihenfolge if werte[k]]
    if v.ust_id_im_kopf and re.ust_id:
        kopf.append((lb["ust_id"], re.ust_id))
    if v.bank_im_kopf and re.iban:
        kopf.append((lb["iban"], re.iban))
    x_label, x_wert = 330.0, 440.0
    for i, (label, wert) in enumerate(kopf):
        c.drawString(x_label, y - i * 13, f"{label}:")
        c.drawString(x_wert, y - i * 13, wert)

    # Titel
    y = hoehe - 250
    c.setFont("Helvetica-Bold", 16)
    c.drawString(links, y, lb["titel"])

    # Positionen
    y -= 30
    # (x, rechtsbuendig) je Spalte: Pos, Artikel, Bezeichnung, Menge, Einheit, Preis, Betrag, USt
    spalten = (
        (links, False), (links + 25, False), (links + 85, False), (links + 285, True),
        (links + 292, False), (links + 385, True), (links + 460, True), (rechts, True),
    )  # fmt: skip
    kopfzeile = (
        "Pos", lb["artikel"], "Bezeichnung", lb["menge"], "Einh.", lb["preis"], lb["betrag"],
        lb["ust"],
    )  # fmt: skip

    def zeile_zeichnen(texte: tuple[str, ...], hoehe_y: float) -> None:
        for (x, rechtsbuendig), text in zip(spalten, texte, strict=True):
            if rechtsbuendig:
                c.drawRightString(x, hoehe_y, text)
            else:
                c.drawString(x, hoehe_y, text)

    c.setFont("Helvetica-Bold", 8.5)
    zeile_zeichnen(kopfzeile, y)
    c.line(links, y - 4, rechts, y - 4)
    c.setFont("Helvetica", 8.5)
    for i, p in enumerate(re.positionen, start=1):
        y -= 15
        zeile_zeichnen(
            (
                str(i),
                p.mat_nr,
                p.bezeichnung[:36],
                str(p.menge),
                p.einheit,
                betrag_text(p.preis_netto, v.zahlenformat),
                betrag_text(p.betrag_netto, v.zahlenformat),
                satz_text(p.ust_satz, v.satzformat),
            ),
            y,
        )
    c.line(links, y - 6, rechts, y - 6)

    # Summen
    y -= 26
    summen: list[tuple[str, str]] = [(lb["netto"], betrag_text(re.netto, v.zahlenformat))]
    for z in re.ust:
        satz, basis = satz_text(z.satz, v.satzformat), betrag_text(z.netto, v.zahlenformat)
        label = f"{lb['ust']} {satz} auf {basis}"
        summen.append((label, betrag_text(z.betrag, v.zahlenformat)))
    for i, (label, wert) in enumerate(summen):
        c.drawString(300, y - i * 14, label)
        c.drawRightString(rechts, y - i * 14, wert)
    y -= len(summen) * 14 + 4
    c.setFont("Helvetica-Bold", 10)
    c.drawString(300, y, lb["brutto"])
    c.drawRightString(rechts, y, betrag_text(re.brutto, v.zahlenformat))

    # Freitext
    if re.freitext:
        y -= 40
        c.setFont("Helvetica", 9)
        c.drawString(links, y, re.freitext)

    # Fußzeile
    fuss: list[str] = []
    if not v.ust_id_im_kopf and re.ust_id:
        fuss.append(f"{lb['ust_id']}: {re.ust_id}")
    if not v.bank_im_kopf and re.iban:
        fuss.append(f"{lb['iban']}: {re.iban}")
    c.setFont("Helvetica", 8)
    c.line(links, 70, rechts, 70)
    c.drawString(links, 56, f"{re.lieferant_name} · {re.lieferant_strasse} · {re.lieferant_ort}")
    if fuss:
        c.drawString(links, 44, " · ".join(fuss))

    c.showPage()
    c.save()
