"""Fachliche Datenobjekte (Spezifikation, Abschnitt 2). Beträge immer als Decimal."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Modell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Lieferant(_Modell):
    kred_nr: str
    name: str
    strasse: str
    ort: str
    ust_id: str
    iban: str
    gesperrt: bool = False


class Material(_Modell):
    mat_nr: str
    bezeichnung: str
    basis_einheit: str = "ST"
    ust_satz: Decimal
    einheiten: dict[str, int] = {}  # z.B. {"KAR": 12}

    def faktor(self, einheit: str) -> int | None:
        """Umrechnungsfaktor in die Basiseinheit, None wenn unbekannt."""
        if einheit == self.basis_einheit:
            return 1
        return self.einheiten.get(einheit)


class BestPos(_Modell):
    pos: int
    mat_nr: str
    menge: int  # Basiseinheit
    preis_netto: Decimal  # pro Basiseinheit


class Bestellung(_Modell):
    best_nr: str
    kred_nr: str
    datum: date
    positionen: tuple[BestPos, ...]


class WePos(_Modell):
    we_nr: str
    best_nr: str
    pos: int
    menge_geliefert: int  # Basiseinheit
    datum: date


class ReHistPos(_Modell):
    best_nr: str
    pos: int
    menge_berechnet: int  # Basiseinheit


class ReHist(_Modell):
    kred_nr: str
    re_nr: str
    best_nr: str
    betrag_brutto: Decimal
    datum: date
    positionen: tuple[ReHistPos, ...]


class Welt(_Modell):
    """Stammdaten und Belege, wie sie im ERP stehen."""

    lieferanten: tuple[Lieferant, ...]
    materialien: tuple[Material, ...]
    bestellungen: tuple[Bestellung, ...]
    wareneingaenge: tuple[WePos, ...]
    re_hist: tuple[ReHist, ...]


class RePos(_Modell):
    mat_nr: str
    bezeichnung: str
    menge: int  # in der berechneten Einheit
    einheit: str
    preis_netto: Decimal  # pro berechneter Einheit
    betrag_netto: Decimal
    ust_satz: Decimal


class UstZeile(_Modell):
    satz: Decimal
    netto: Decimal
    betrag: Decimal


class Rechnung(_Modell):
    """Inhalt einer Rechnung, so wie er auf dem PDF steht."""

    re_nr: str
    datum: date
    lieferant_name: str
    lieferant_strasse: str
    lieferant_ort: str
    ust_id: str | None
    best_nr: str | None
    iban: str | None
    positionen: tuple[RePos, ...]
    netto: Decimal
    ust: tuple[UstZeile, ...]
    brutto: Decimal
    freitext: str | None = None
