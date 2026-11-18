"""Lieferanten und Materialien (Spezifikation 7.1). Alle Namen sind frei erfunden."""

import random
from decimal import Decimal

from invoice_agent import normalize
from invoice_agent.model import Lieferant, Material

_NACHNAMEN = (
    "Müller", "Schröder", "Köhler", "Weiß", "Krüger", "Bäumer", "Schäfer", "Größmann",
    "Becker", "Hoffmann", "Wagner", "Brandt", "Lindner", "Vogt", "Hartmann", "Engel",
    "Jürgens", "Möller", "Löffler", "Hübner",
)  # fmt: skip
_BRANCHEN = (
    "Industriebedarf", "Bürotechnik", "Logistik", "Elektrotechnik", "Verpackung", "Werkzeuge",
    "Lebensmittel", "Hygiene", "Metallbau", "Druckerei", "Laborbedarf", "Arbeitsschutz",
)  # fmt: skip
_RECHTSFORMEN = ("GmbH", "GmbH & Co. KG", "AG", "KG", "e.K.", "UG (haftungsbeschränkt)")
_STRASSEN = ("Hauptstraße", "Industriestraße", "Am Hafen", "Gewerbering", "Lindenweg", "Kanalstr.")
_ORTE = (
    "20457 Hamburg", "28195 Bremen", "30159 Hannover", "44135 Dortmund", "50667 Köln",
    "60311 Frankfurt am Main", "70173 Stuttgart", "80331 München", "90402 Nürnberg",
    "04109 Leipzig", "01067 Dresden", "24103 Kiel",
)  # fmt: skip

_ARTIKEL_19 = (
    "Sechskantschraube M8", "Kabelbinder 300 mm", "Druckerpapier A4", "Toner schwarz",
    "Schutzhandschuhe Gr. 9", "Klebeband 50 mm", "Palettenfolie", "Akkuschrauber 18 V",
    "Kugellager 6204", "Hydrauliköl 5 l", "Etiketten 100x50", "Warnweste gelb",
    "Wellpappkarton 40x30", "Steckdosenleiste 6-fach", "LED-Röhre 120 cm", "Schleifscheibe 125 mm",
    "Desinfektionsmittel 1 l", "Ordner breit", "Flachdichtung DN50", "Bohrer-Set HSS",
)  # fmt: skip
_ARTIKEL_7 = (
    "Kaffee 1 kg", "Mineralwasser 0,5 l", "Fachbuch Logistik", "Tee-Sortiment",
    "Milch 1 l", "Apfelsaft 1 l", "Fachzeitschrift Abo", "Kekse 200 g",
)  # fmt: skip


def _iban(rng: random.Random) -> str:
    """Formal gültige deutsche IBAN (Prüfziffer nach ISO 13616, Bankleitzahl erfunden)."""
    bban = "".join(str(rng.randint(0, 9)) for _ in range(18))
    rest = int(bban + "131400")  # "DE00" → D=13, E=14, 00
    pruef = 98 - rest % 97
    return f"DE{pruef:02d}{bban}"


def neue_ust_id(rng: random.Random, vergeben: set[str]) -> str:
    while True:
        kandidat = "DE" + "".join(str(rng.randint(0, 9)) for _ in range(9))
        if kandidat not in vergeben:
            vergeben.add(kandidat)
            return kandidat


def neue_iban(rng: random.Random, vergeben: set[str]) -> str:
    while True:
        kandidat = _iban(rng)
        if kandidat not in vergeben:
            vergeben.add(kandidat)
            return kandidat


def lieferanten(rng: random.Random, anzahl: int, gesperrt: int) -> tuple[list[Lieferant], set[str]]:
    """Liefert Lieferanten und die Menge der vergebenen USt-IDs und IBANs."""
    namen: set[str] = set()
    vergeben: set[str] = set()
    ergebnis: list[Lieferant] = []
    while len(ergebnis) < anzahl:
        name = f"{rng.choice(_NACHNAMEN)} {rng.choice(_BRANCHEN)} {rng.choice(_RECHTSFORMEN)}"
        kern = normalize.lieferantenname(name)
        if kern in namen:
            continue
        namen.add(kern)
        nr = len(ergebnis) + 1
        ergebnis.append(
            Lieferant(
                kred_nr=f"K{10000 + nr}",
                name=name,
                strasse=f"{rng.choice(_STRASSEN)} {rng.randint(1, 120)}",
                ort=rng.choice(_ORTE),
                ust_id=neue_ust_id(rng, vergeben),
                iban=neue_iban(rng, vergeben),
                gesperrt=nr > anzahl - gesperrt,
            )
        )
    return ergebnis, vergeben


def materialien(rng: random.Random, anzahl: int) -> list[Material]:
    ergebnis: list[Material] = []
    for i in range(anzahl):
        ermaessigt = rng.random() < 0.30
        basis = rng.choice(_ARTIKEL_7 if ermaessigt else _ARTIKEL_19)
        einheiten = {"KAR": rng.choice((6, 10, 12, 24))} if rng.random() < 0.25 else {}
        ergebnis.append(
            Material(
                mat_nr=f"M-{20001 + i}",
                bezeichnung=f"{basis} ({chr(65 + i % 26)}{i // 26 + 1})",
                ust_satz=Decimal("7") if ermaessigt else Decimal("19"),
                einheiten=einheiten,
            )
        )
    return ergebnis
