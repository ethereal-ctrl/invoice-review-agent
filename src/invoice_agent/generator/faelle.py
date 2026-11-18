"""Fälle erzeugen (Spezifikation 7.2).

Jeder Fall bekommt eine eigene Bestellung samt Wareneingang. Der eingespielte Typ legt
fest, welche Codes erwartet werden. Die Gold-Codes werden aber mit dem Regelwerk
(`pruefung.py`) aus den wahren Daten berechnet. Stimmen beide nicht überein, wird der Fall
verworfen und neu gezogen (Verwerfungs-Sampling). Am Ende wird die gesamte Welt noch einmal
geprüft, damit spätere Fälle frühere nicht verändert haben.
"""

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict

from invoice_agent import normalize
from invoice_agent.config import Settings
from invoice_agent.domain import Code, Entscheidung, entscheide
from invoice_agent.generator import stammdaten
from invoice_agent.gold import Gold
from invoice_agent.model import (
    Bestellung,
    BestPos,
    Lieferant,
    Material,
    Rechnung,
    ReHist,
    ReHistPos,
    RePos,
    UstZeile,
    Welt,
    WePos,
)
from invoice_agent.pruefung import Index, pruefe

CENT = Decimal("0.01")

TYPEN = ("F1", "F2", "F3", "F4", "F5", "F6", "H1", "H2", "H3", "H4", "SAUBER")
VERTEILUNG: dict[str, int] = {
    **{t: 20 for t in ("F1", "F2", "F3", "F4", "F5", "F6")},
    **{t: 15 for t in ("H1", "H2", "H3", "H4")},
    "SAUBER": 120,
}
ERWARTET: dict[str, frozenset[Code]] = {
    "F1": frozenset({Code.F1}),
    "F2": frozenset({Code.F2}),
    "F3": frozenset({Code.F3, Code.F2}),
    "F4": frozenset({Code.F4}),
    "F5": frozenset({Code.F5}),
    "F6": frozenset({Code.F6}),
    **{t: frozenset() for t in ("H1", "H2", "H3", "H4", "SAUBER")},
}

ANZAHL_LIEFERANTEN = 40
ANZAHL_GESPERRT = 2
ANZAHL_MATERIALIEN = 80
MAX_VERSUCHE = 50

_NEUTRAL = (
    "Vielen Dank für Ihren Auftrag.",
    "Lieferung frei Haus.",
    "Zahlbar innerhalb von 30 Tagen ohne Abzug.",
    "Bei Rückfragen erreichen Sie uns unter der oben genannten Adresse.",
    "Wir danken für die gute Zusammenarbeit.",
)
_BANK = (
    "Bitte beachten Sie unsere neue Bankverbindung.",
    "Unsere Bankverbindung hat sich geändert. Bitte überweisen Sie nur noch auf das "
    "unten genannte Konto.",
)
_RE_FORMATE = ("RE-{j}-{n:05d}", "{n:06d}", "INV{n:05d}", "R{j}{n:04d}", "{j}/{n:05d}")


class _Modell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Fall(_Modell):
    fall_id: str
    rechnung: Rechnung
    gold: Gold


@dataclass
class _Kandidat:
    rechnung: Rechnung
    bestellung: Bestellung
    wareneingaenge: list[WePos]
    historie: list[ReHist] = field(default_factory=list[ReHist])
    abweichung: Decimal = Decimal(0)
    variante: str | None = None


@dataclass
class _Kontext:
    settings: Settings
    lieferanten: list[Lieferant]
    aktive: list[Lieferant]
    materialien: list[Material]
    vergeben: set[str]
    bestellungen: list[Bestellung] = field(default_factory=list[Bestellung])
    wareneingaenge: list[WePos] = field(default_factory=list[WePos])
    historie: list[ReHist] = field(default_factory=list[ReHist])
    naechste_best: int = 4500010000
    naechster_we: int = 5000010000
    re_zaehler: dict[str, int] = field(default_factory=dict[str, int])
    verworfen: dict[str, int] = field(default_factory=dict[str, int])

    def welt(self, extra: _Kandidat | None = None) -> Welt:
        best = [*self.bestellungen, *([extra.bestellung] if extra else [])]
        we = [*self.wareneingaenge, *(extra.wareneingaenge if extra else [])]
        hist = [*self.historie, *(extra.historie if extra else [])]
        return Welt(
            lieferanten=tuple(self.lieferanten),
            materialien=tuple(self.materialien),
            bestellungen=tuple(best),
            wareneingaenge=tuple(we),
            re_hist=tuple(hist),
        )

    def re_nr(self, lieferant: Lieferant, datum: date) -> str:
        nr = int(lieferant.kred_nr[1:])
        n = self.re_zaehler.get(lieferant.kred_nr, 1000 + (nr * 37) % 900) + 1
        self.re_zaehler[lieferant.kred_nr] = n
        return _RE_FORMATE[nr % len(_RE_FORMATE)].format(j=datum.year, n=n)


# ---------------------------------------------------------------- Bausteine


def _geld(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _bestellung(
    ctx: _Kontext, rng: random.Random, lieferant: Lieferant, mit_einheit: bool = False
) -> Bestellung:
    anzahl = rng.randint(1, 5)
    mats = rng.sample(ctx.materialien, anzahl)
    if mit_einheit and not any(m.einheiten for m in mats):
        mats[0] = rng.choice([m for m in ctx.materialien if m.einheiten and m not in mats])

    # Kartonware ist Verbrauchsmaterial und pro Stück günstig.
    preise = [
        Decimal(str(round(rng.uniform(0.5, 15.0) if m.einheiten else rng.uniform(1.5, 250.0), 2)))
        for m in mats
    ]
    roh = [rng.randint(2, 60) for _ in mats]
    netto_roh = sum((Decimal(m) * p for m, p in zip(roh, preise, strict=True)), Decimal(0))
    gross = rng.random() < 0.20  # ergibt ~20 % über 5.000 € brutto (Spezifikation 7.1)
    ziel = Decimal(str(rng.uniform(4300, 12000) if gross else rng.uniform(120, 3800)))
    skala = ziel / netto_roh

    positionen: list[BestPos] = []
    for i, (mat, menge, preis) in enumerate(zip(mats, roh, preise, strict=True), start=1):
        menge_neu = max(1, round(menge * skala))
        if mat.einheiten:
            faktor = mat.einheiten["KAR"]
            menge_neu = max(1, round(menge_neu / faktor)) * faktor
        positionen.append(BestPos(pos=i, mat_nr=mat.mat_nr, menge=menge_neu, preis_netto=preis))

    datum = date(2026, 9, 1) + timedelta(days=rng.randint(0, 60))
    nr = ctx.naechste_best
    ctx.naechste_best += 1
    return Bestellung(
        best_nr=str(nr), kred_nr=lieferant.kred_nr, datum=datum, positionen=tuple(positionen)
    )


def _wareneingang(
    ctx: _Kontext, rng: random.Random, best: Bestellung, mengen: dict[int, int]
) -> list[WePos]:
    nr = ctx.naechster_we
    ctx.naechster_we += 1
    datum = best.datum + timedelta(days=rng.randint(3, 20))
    return [
        WePos(we_nr=str(nr), best_nr=best.best_nr, pos=p, menge_geliefert=m, datum=datum)
        for p, m in mengen.items()
        if m > 0
    ]


def _positionen(
    ctx: _Kontext,
    best: Bestellung,
    mengen: dict[int, int],
    karton: frozenset[int] = frozenset(),
    preisfaktor: dict[int, Decimal] | None = None,
) -> list[RePos]:
    material = {m.mat_nr: m for m in ctx.materialien}
    ergebnis: list[RePos] = []
    for bp in best.positionen:
        menge_st = mengen.get(bp.pos, 0)
        if menge_st <= 0:
            continue
        mat = material[bp.mat_nr]
        preis_st = bp.preis_netto * (preisfaktor or {}).get(bp.pos, Decimal(1))
        if bp.pos in karton:
            faktor = mat.einheiten["KAR"]
            menge, einheit, preis = menge_st // faktor, "KAR", _geld(preis_st * faktor)
        else:
            menge, einheit, preis = menge_st, "ST", _geld(preis_st)
        ergebnis.append(
            RePos(
                mat_nr=mat.mat_nr,
                bezeichnung=mat.bezeichnung,
                menge=menge,
                einheit=einheit,
                preis_netto=preis,
                betrag_netto=_geld(menge * preis),
                ust_satz=mat.ust_satz,
            )
        )
    return ergebnis


def _rechnung(
    lieferant: Lieferant,
    best: Bestellung | None,
    positionen: list[RePos],
    datum: date,
    re_nr: str,
    iban: str | None,
    *,
    ust_id: str | None = None,
    name: str | None = None,
    freitext: str | None = None,
    brutto_delta: Decimal = Decimal(0),
) -> Rechnung:
    netto = sum((p.betrag_netto for p in positionen), Decimal(0))
    saetze = sorted({p.ust_satz for p in positionen}, reverse=True)
    ust: list[UstZeile] = []
    for satz in saetze:
        basis = sum((p.betrag_netto for p in positionen if p.ust_satz == satz), Decimal(0))
        ust.append(UstZeile(satz=satz, netto=basis, betrag=_geld(basis * satz / 100)))
    brutto = netto + sum((z.betrag for z in ust), Decimal(0)) + brutto_delta
    return Rechnung(
        re_nr=re_nr,
        datum=datum,
        lieferant_name=name or lieferant.name,
        lieferant_strasse=lieferant.strasse,
        lieferant_ort=lieferant.ort,
        ust_id=lieferant.ust_id if ust_id is None else (ust_id or None),
        best_nr=best.best_nr if best else None,
        iban=iban,
        positionen=tuple(positionen),
        netto=netto,
        ust=tuple(ust),
        brutto=brutto,
        freitext=freitext,
    )


def _iban_drucken(rng: random.Random, lieferant: Lieferant) -> str | None:
    return lieferant.iban if rng.random() < 0.8 else None


def _neutral(rng: random.Random) -> str | None:
    return rng.choice(_NEUTRAL) if rng.random() < 0.3 else None


def _voll(best: Bestellung) -> dict[int, int]:
    return {p.pos: p.menge for p in best.positionen}


def _basis(
    ctx: _Kontext, rng: random.Random, *, mit_einheit: bool = False
) -> tuple[Lieferant, Bestellung, list[WePos], date]:
    lieferant = rng.choice(ctx.aktive)
    best = _bestellung(ctx, rng, lieferant, mit_einheit=mit_einheit)
    we = _wareneingang(ctx, rng, best, _voll(best))
    datum = we[0].datum + timedelta(days=rng.randint(0, 10))
    return lieferant, best, we, datum


def _korrekt(
    ctx: _Kontext, lieferant: Lieferant, best: Bestellung, mengen: dict[int, int]
) -> Decimal:
    """Bruttobetrag einer fehlerfreien Rechnung über die gelieferten Mengen."""
    pos = _positionen(ctx, best, mengen)
    return _rechnung(lieferant, best, pos, best.datum, "X", None).brutto


# ---------------------------------------------------------------- Fehlertypen


def _sauber(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng)
    pos = _positionen(ctx, best, _voll(best))
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), freitext=_neutral(rng),
    )  # fmt: skip
    return _Kandidat(re, best, we)


def _h1_teillieferung(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant = rng.choice(ctx.aktive)
    best = _bestellung(ctx, rng, lieferant)
    geliefert = _voll(best)
    teil = rng.sample(list(geliefert), rng.randint(1, len(geliefert)))
    for p in teil:
        geliefert[p] = max(1, round(geliefert[p] * rng.uniform(0.4, 0.8)))
    we = _wareneingang(ctx, rng, best, geliefert)
    datum = we[0].datum + timedelta(days=rng.randint(0, 10))
    kw = (datum + timedelta(days=rng.randint(7, 21))).isocalendar().week
    text = f"Teillieferung, Rest folgt in KW {kw}." if rng.random() < 0.7 else _neutral(rng)
    pos = _positionen(ctx, best, geliefert)
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), freitext=text,
    )  # fmt: skip
    return _Kandidat(re, best, we)


def _h2_karton(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng, mit_einheit=True)
    material = {m.mat_nr: m for m in ctx.materialien}
    karton = frozenset(p.pos for p in best.positionen if material[p.mat_nr].einheiten)
    pos = _positionen(ctx, best, _voll(best), karton=karton)
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), freitext=_neutral(rng),
    )  # fmt: skip
    return _Kandidat(re, best, we)


def _preis(ctx: _Kontext, rng: random.Random, von: float, bis: float) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng)
    ziel = rng.choice(best.positionen).pos
    faktor = {ziel: Decimal(str(round(1 + rng.uniform(von, bis), 4)))}
    pos = _positionen(ctx, best, _voll(best), preisfaktor=faktor)
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), freitext=_neutral(rng),
    )  # fmt: skip
    abweichung = abs(re.brutto - _korrekt(ctx, lieferant, best, _voll(best)))
    return _Kandidat(re, best, we, abweichung=abweichung)


def _h3_preis_in_toleranz(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    return _preis(ctx, rng, 0.001, 0.018)


def _f1_preis_ueber_toleranz(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    return _preis(ctx, rng, 0.03, 0.15)


def _namensvariante(rng: random.Random, name: str) -> str:
    ersatz = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"}
    rechtsformen = ("GmbH & Co. KG", "UG (haftungsbeschränkt)", "GmbH", "AG", "KG", "e.K.")
    for _ in range(20):
        neu = name
        if any(c in neu for c in ersatz) and rng.random() < 0.7:
            neu = "".join(ersatz.get(c, c) for c in neu)
        if rng.random() < 0.6:
            for rf in rechtsformen:
                if neu.endswith(" " + rf):
                    neu = neu[: -len(rf)] + rng.choice([r for r in rechtsformen if r != rf])
                    break
        if rng.random() < 0.3:
            neu = neu.upper()
        if neu != name and normalize.lieferantenname(neu) == normalize.lieferantenname(name):
            return neu
    return name.upper()


def _h4_namensvariante(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng)
    pos = _positionen(ctx, best, _voll(best))
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), name=_namensvariante(rng, lieferant.name),
        freitext=_neutral(rng),
    )  # fmt: skip
    return _Kandidat(re, best, we)


def _f2_mehr_als_geliefert(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng)
    geliefert = _voll(best)
    berechnet = dict(geliefert)
    ziel = rng.choice(list(berechnet))
    berechnet[ziel] = max(geliefert[ziel] + 1, math.ceil(geliefert[ziel] * rng.uniform(1.05, 1.30)))
    pos = _positionen(ctx, best, berechnet)
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), freitext=_neutral(rng),
    )  # fmt: skip
    abweichung = abs(re.brutto - _korrekt(ctx, lieferant, best, geliefert))
    return _Kandidat(re, best, we, abweichung=abweichung)


def _nummer_variante(rng: random.Random, alt: str) -> tuple[str, str]:
    if rng.random() < 0.5:
        stelle = rng.randint(1, len(alt) - 1)
        neu = alt[:stelle] + rng.choice(("-", " ", "/")) + alt[stelle:]
        return (neu.lower() if rng.random() < 0.3 else neu), "format"
    return alt + rng.choice(("-A", "/2", "-B", " a")), "suffix"


def _f3_doppelrechnung(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, _ = _basis(ctx, rng)
    alt_datum = we[0].datum + timedelta(days=rng.randint(1, 5))
    original = _rechnung(
        lieferant, best, _positionen(ctx, best, _voll(best)), alt_datum,
        ctx.re_nr(lieferant, alt_datum), lieferant.iban,
    )  # fmt: skip
    hist = ReHist(
        kred_nr=lieferant.kred_nr,
        re_nr=original.re_nr,
        best_nr=best.best_nr,
        betrag_brutto=original.brutto,
        datum=alt_datum,
        positionen=tuple(
            ReHistPos(best_nr=best.best_nr, pos=p, menge_berechnet=m)
            for p, m in _voll(best).items()
        ),
    )
    if rng.random() < 0.3:
        datum = alt_datum + timedelta(days=rng.randint(1, 25))
        re_nr, variante = ctx.re_nr(lieferant, datum), "bestellung_datum"
    else:
        datum = alt_datum + timedelta(days=rng.randint(0, 40))
        re_nr, variante = _nummer_variante(rng, original.re_nr)
    re = original.model_copy(
        update={"re_nr": re_nr, "datum": datum, "iban": _iban_drucken(rng, lieferant)}
    )
    return _Kandidat(re, best, we, [hist], abweichung=re.brutto, variante=variante)


def _f4_steuer_rechenfehler(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng)
    pos = _positionen(ctx, best, _voll(best))
    korrekt = _rechnung(lieferant, best, pos, datum, "X", None).brutto
    variante = rng.choice(("satz", "position", "brutto"))
    delta = Decimal(0)
    if variante == "satz":
        i = rng.randrange(len(pos))
        neu = Decimal("7") if pos[i].ust_satz == Decimal("19") else Decimal("19")
        pos[i] = pos[i].model_copy(update={"ust_satz": neu})
    elif variante == "position":
        i = rng.randrange(len(pos))
        obergrenze = max(0.6, min(50.0, float(pos[i].betrag_netto) * 0.5))
        fehler = Decimal(str(round(rng.uniform(0.5, obergrenze), 2))) * rng.choice((1, -1))
        pos[i] = pos[i].model_copy(update={"betrag_netto": pos[i].betrag_netto + fehler})
    else:
        delta = Decimal(str(round(rng.uniform(1.0, 100.0), 2))) * rng.choice((1, -1))
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), freitext=_neutral(rng), brutto_delta=delta,
    )  # fmt: skip
    return _Kandidat(re, best, we, abweichung=abs(re.brutto - korrekt), variante=variante)


def _f5_iban(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng)
    pos = _positionen(ctx, best, _voll(best))
    mit_text = rng.random() < 0.5
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        stammdaten.neue_iban(rng, ctx.vergeben),
        freitext=rng.choice(_BANK) if mit_text else _neutral(rng),
    )  # fmt: skip
    variante = "mit_hinweis" if mit_text else "ohne_hinweis"
    return _Kandidat(re, best, we, abweichung=re.brutto, variante=variante)


def _f6_lieferant(ctx: _Kontext, rng: random.Random) -> _Kandidat:
    lieferant, best, we, datum = _basis(ctx, rng)
    pos = _positionen(ctx, best, _voll(best))
    variante = rng.choice(("fehlt", "unbekannt", "fremd"))
    if variante == "fehlt":
        ust_id = ""
    elif variante == "unbekannt":
        ust_id = stammdaten.neue_ust_id(rng, ctx.vergeben)
    else:
        ust_id = rng.choice([lf for lf in ctx.aktive if lf.kred_nr != lieferant.kred_nr]).ust_id
    re = _rechnung(
        lieferant, best, pos, datum, ctx.re_nr(lieferant, datum),
        _iban_drucken(rng, lieferant), ust_id=ust_id, freitext=_neutral(rng),
    )  # fmt: skip
    return _Kandidat(re, best, we, abweichung=re.brutto, variante=variante)


_BAUER: dict[str, Callable[[_Kontext, random.Random], _Kandidat]] = {
    "SAUBER": _sauber,
    "H1": _h1_teillieferung,
    "H2": _h2_karton,
    "H3": _h3_preis_in_toleranz,
    "H4": _h4_namensvariante,
    "F1": _f1_preis_ueber_toleranz,
    "F2": _f2_mehr_als_geliefert,
    "F3": _f3_doppelrechnung,
    "F4": _f4_steuer_rechenfehler,
    "F5": _f5_iban,
    "F6": _f6_lieferant,
}


# ---------------------------------------------------------------- Splits


def _dev_anteile(gesamt: int, dev: int) -> dict[str, int]:
    """Dev-Anzahl pro Typ, proportional nach dem Verfahren der größten Reste."""
    quote = {t: VERTEILUNG[t] * dev / gesamt for t in TYPEN}
    anteile = {t: math.floor(q) for t, q in quote.items()}
    rest = dev - sum(anteile.values())
    for t in sorted(TYPEN, key=lambda t: (-(quote[t] - anteile[t]), TYPEN.index(t)))[:rest]:
        anteile[t] += 1
    return anteile


# ---------------------------------------------------------------- Einstieg


@dataclass(frozen=True)
class Ergebnis:
    welt: Welt
    faelle: list[Fall]
    verworfen: dict[str, int]  # verworfene Versuche pro Typ (Transparenz im Manifest)


def erzeuge(settings: Settings) -> Ergebnis:
    g = settings.generator
    if sum(VERTEILUNG.values()) != g.anzahl:
        raise ValueError(
            f"Verteilung ergibt {sum(VERTEILUNG.values())}, Config verlangt {g.anzahl}"
        )

    rng = random.Random(g.seed)
    lieferanten, vergeben = stammdaten.lieferanten(rng, ANZAHL_LIEFERANTEN, ANZAHL_GESPERRT)
    ctx = _Kontext(
        settings=settings,
        lieferanten=lieferanten,
        aktive=[lf for lf in lieferanten if not lf.gesperrt],
        materialien=stammdaten.materialien(rng, ANZAHL_MATERIALIEN),
        vergeben=vergeben,
    )

    roh: list[tuple[str, _Kandidat]] = []
    for typ in TYPEN:
        for k in range(VERTEILUNG[typ]):
            roh.append((typ, _ziehe(ctx, typ, k)))

    # Splits (geschichtet) und Fall-IDs
    anteile = _dev_anteile(g.anzahl, g.dev)
    split: list[str] = []
    for typ in TYPEN:
        n = VERTEILUNG[typ]
        markierung = ["dev"] * anteile[typ] + ["test"] * (n - anteile[typ])
        rng.shuffle(markierung)
        split.extend(markierung)
    # Layout C: die Hälfte der Test-Fälle jedes Typs, eigener Zufallsstrom (Fall-IDs bleiben gleich)
    layout = ["A"] * len(roh)
    rng_layout = random.Random(f"{g.seed}:layout")
    start = 0
    for typ in TYPEN:
        test_idx = [i for i in range(start, start + VERTEILUNG[typ]) if split[i] == "test"]
        rng_layout.shuffle(test_idx)
        for i in test_idx[: len(test_idx) // 2]:
            layout[i] = "C"
        start += VERTEILUNG[typ]
    reihenfolge = list(range(len(roh)))
    rng.shuffle(reihenfolge)

    smoke = _smoke_auswahl([(roh[i][0], split[i]) for i in reihenfolge], g.smoke)

    welt = ctx.welt()
    idx = Index(welt)
    faelle: list[Fall] = []
    for nr, i in enumerate(reihenfolge, start=1):
        typ, kand = roh[i]
        fall_id = f"FALL-{nr:04d}"
        codes = pruefe(kand.rechnung, idx, settings.toleranzen)
        if codes != ERWARTET[typ]:
            raise RuntimeError(f"{fall_id} ({typ}): Gold {sorted(codes)} ≠ erwartet")
        entscheidung = entscheide(codes)
        gold = Gold(
            fall_id=fall_id,
            split=split[i],
            smoke=(nr - 1) in smoke,
            typ=typ,
            variante=kand.variante,
            entscheidung=entscheidung,
            codes=tuple(sorted(codes)),
            brutto=kand.rechnung.brutto,
            abweichung_eur=Decimal(0)
            if entscheidung is Entscheidung.FREIGEBEN
            else kand.abweichung,
            layout=layout[i],
        )
        faelle.append(Fall(fall_id=fall_id, rechnung=kand.rechnung, gold=gold))
    return Ergebnis(welt=welt, faelle=faelle, verworfen=dict(ctx.verworfen))


def _ziehe(ctx: _Kontext, typ: str, k: int) -> _Kandidat:
    seed = ctx.settings.generator.seed
    for versuch in range(MAX_VERSUCHE):
        rng = random.Random(f"{seed}:{typ}:{k}:{versuch}")
        kand = _BAUER[typ](ctx, rng)
        if pruefe(kand.rechnung, Index(ctx.welt(kand)), ctx.settings.toleranzen) == ERWARTET[typ]:
            ctx.bestellungen.append(kand.bestellung)
            ctx.wareneingaenge.extend(kand.wareneingaenge)
            ctx.historie.extend(kand.historie)
            return kand
        ctx.verworfen[typ] = ctx.verworfen.get(typ, 0) + 1
    raise RuntimeError(f"Typ {typ}: nach {MAX_VERSUCHE} Versuchen kein passender Fall")


def _smoke_auswahl(geordnet: list[tuple[str, str]], groesse: int) -> set[int]:
    """Je ein Dev-Fall pro Fehlertyp und harmloser Variante, Rest saubere Dev-Fälle."""
    gewaehlt: set[int] = set()
    for typ in TYPEN[:-1]:
        for pos, (t, s) in enumerate(geordnet):
            if t == typ and s == "dev":
                gewaehlt.add(pos)
                break
    for pos, (t, s) in enumerate(geordnet):
        if len(gewaehlt) >= groesse:
            break
        if t == "SAUBER" and s == "dev":
            gewaehlt.add(pos)
    return gewaehlt
