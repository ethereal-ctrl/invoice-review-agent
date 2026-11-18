"""Extraktion ohne LLM: PDF-Text mit regulären Ausdrücken in eine Rechnung überführen.

Die Muster decken genau die Feldbezeichnungen und Formate ab, die in den Dev-PDFs vorkommen.
Weil Generator und Extraktion im selben Projekt entstehen, kennt diese Stufe das eine Layout
praktisch vollständig. Das ist eine bekannte Grenze von v1 (siehe Bericht, Abschnitt Grenzen).
Ein unbekanntes Format führt zu einem `ExtraktionsFehler`, nie zu geratenen Werten.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from invoice_agent.model import Rechnung, RePos, UstZeile

_BETRAG = r"(?:EUR -?\d{1,3}(?: \d{3})*,\d{2}|-?\d{1,3}(?:\.\d{3})+,\d{2} €|-?\d+,\d{2} (?:€|EUR))"

_KOPF = {
    "re_nr": r"(?:Rechnungsnummer|Rechnungsnr\.|Beleg-Nr\.|Invoice No\.):[ ]*(.+?)[ ]*$",
    "datum": r"(?:Rechnungsdatum|Belegdatum|Invoice Date|Datum):[ ]*(.+?)[ ]*$",
    "best_nr": r"(?:Bestellnr\.|Ihre Bestellung|Auftragsnr\.|PO):[ ]*(\d+)",
    "ust_id": r"(?:USt-IdNr\.|USt-ID|VAT ID):[ ]*([A-Z]{2}[0-9A-Z]+)",
    "iban": r"(?:Konto \(IBAN\)|Bankverbindung IBAN|IBAN):[ ]*([A-Z]{2}\d{2}[0-9A-Z]+)",
}
_POSITION = re.compile(
    rf"^(\d+) (\S+) (.+) (\d+) (\S+) ({_BETRAG}) ({_BETRAG}) (\d+) ?%$", re.MULTILINE
)
_NETTO = re.compile(rf"^(?:Nettobetrag|Summe netto|Zwischensumme|Net total) ({_BETRAG})$", re.M)
_UST = re.compile(rf"^(?:USt|MwSt|Umsatzsteuer|VAT) (\d+) ?% auf ({_BETRAG}) ({_BETRAG})$", re.M)
_BRUTTO = re.compile(
    rf"^(?:Gesamtbetrag|Rechnungsbetrag|Summe brutto|Total) ({_BETRAG})$", re.MULTILINE
)
_MONATE = {
    "Jan.": 1, "Feb.": 2, "März": 3, "Apr.": 4, "Mai": 5, "Juni": 6,
    "Juli": 7, "Aug.": 8, "Sep.": 9, "Okt.": 10, "Nov.": 11, "Dez.": 12,
}  # fmt: skip


class ExtraktionsFehler(ValueError):
    pass


def betrag(text: str) -> Decimal:
    roh = text.replace("EUR", "").replace("€", "").strip()
    if "," not in roh:
        raise ExtraktionsFehler(f"Betrag ohne Dezimalkomma: {text!r}")
    ganz, nachkomma = roh.rsplit(",", 1)
    ganz = ganz.replace(".", "").replace(" ", "")
    try:
        return Decimal(f"{ganz}.{nachkomma}")
    except InvalidOperation as e:
        raise ExtraktionsFehler(f"Betrag nicht lesbar: {text!r}") from e


def datum(text: str) -> date:
    if m := re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", text):
        return date(int(m[3]), int(m[2]), int(m[1]))
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if (m := re.fullmatch(r"(\d{1,2})\. (\S+) (\d{4})", text)) and m[2] in _MONATE:
        return date(int(m[3]), _MONATE[m[2]], int(m[1]))
    raise ExtraktionsFehler(f"Datum nicht lesbar: {text!r}")


def _kopf(text: str, feld: str) -> str | None:
    m = re.search(_KOPF[feld], text, re.MULTILINE)
    return m[1] if m else None


def aus_text(text: str) -> Rechnung:
    zeilen = text.splitlines()
    if len(zeilen) < 2 or " · " not in zeilen[1]:
        raise ExtraktionsFehler("Absenderblock nicht gefunden")
    strasse, _, ort = zeilen[1].partition(" · ")

    re_nr, datum_text = _kopf(text, "re_nr"), _kopf(text, "datum")
    if not re_nr or not datum_text:
        raise ExtraktionsFehler("Rechnungsnummer oder Datum fehlt")

    positionen = [
        RePos(
            mat_nr=m[2],
            bezeichnung=m[3],
            menge=int(m[4]),
            einheit=m[5],
            preis_netto=betrag(m[6]),
            betrag_netto=betrag(m[7]),
            ust_satz=Decimal(m[8]),
        )
        for m in _POSITION.finditer(text)
    ]
    if not positionen:
        raise ExtraktionsFehler("Keine Positionen gefunden")

    netto, brutto = _NETTO.search(text), _BRUTTO.search(text)
    if not netto or not brutto:
        raise ExtraktionsFehler("Netto- oder Bruttobetrag fehlt")
    ust = tuple(
        UstZeile(satz=Decimal(m[1]), netto=betrag(m[2]), betrag=betrag(m[3]))
        for m in _UST.finditer(text)
    )

    return Rechnung(
        re_nr=re_nr,
        datum=datum(datum_text),
        lieferant_name=zeilen[0].strip(),
        lieferant_strasse=strasse.strip(),
        lieferant_ort=ort.strip(),
        ust_id=_kopf(text, "ust_id"),
        best_nr=_kopf(text, "best_nr"),
        iban=_kopf(text, "iban"),
        positionen=tuple(positionen),
        netto=betrag(netto[1]),
        ust=ust,
        brutto=betrag(brutto[1]),
        freitext=None,  # R14: Freitext ist für die Entscheidung irrelevant
    )


def aus_pdf(pfad: Path) -> Rechnung:
    with pdfplumber.open(pfad) as pdf:
        text = "\n".join(seite.extract_text() or "" for seite in pdf.pages)
    return aus_text(text)
