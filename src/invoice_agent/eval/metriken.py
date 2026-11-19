"""Kostenmatrix und Metriken (Plan 3.3 und 4.4).

Die Kosten eines Falls hängen von der Gold-Entscheidung und der *effektiven* Entscheidung
des Systems ab. Effektiv heißt: Legt das System einen Fall einem Menschen vor (`interrupt`),
zählt das als ESKALIEREN.
"""

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from invoice_agent.config import KostenConfig
from invoice_agent.domain import Code, Entscheidung
from invoice_agent.gold import Gold

F, Z, E = Entscheidung.FREIGEBEN, Entscheidung.ZURUECKHALTEN, Entscheidung.ESKALIEREN


class Vorhersage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fall_id: str
    entscheidung: Entscheidung  # Entscheidung des Systems vor der Kompetenzregel
    codes: tuple[Code, ...] = ()
    interrupt: bool = False  # einem Menschen vorgelegt (R15 oder Policy)
    extraktion_ok: bool = True
    fehler: str | None = None
    policy_regel: str | None = None  # Regel der Policy-Middleware, die entschieden hat
    brutto: Decimal | None = None  # gelesener Rechnungsbetrag (für die Freigabe-Ansicht)
    aus_cache: bool = False  # alle LLM-Antworten aus dem Cache: Latenz nicht aussagekräftig
    tokens_ein: int = 0
    tokens_aus: int = 0
    kosten_tokens_eur: Decimal = Decimal(0)
    latenz_ms: float = 0.0

    @property
    def effektiv(self) -> Entscheidung:
        return E if self.interrupt else self.entscheidung


def kosten(gold: Gold, v: Vorhersage, k: KostenConfig) -> Decimal:
    """Kosten eines Falls in EUR laut Kostenmatrix (ohne Token-Kosten)."""
    ist, soll = v.effektiv, gold.entscheidung
    if ist == soll:
        return Decimal(0)
    if soll is F:
        return k.zurueckhalten_statt_freigeben if ist is Z else k.eskalieren_unnoetig
    if soll is Z:
        return gold.abweichung_eur if ist is F else k.eskalieren_unnoetig
    return gold.brutto if ist is F else k.zurueckhalten_statt_eskalieren


def ist_unsicher(gold: Gold, v: Vorhersage) -> bool:
    """Freigabe, obwohl die Gold-Entscheidung nicht FREIGEBEN ist."""
    return v.effektiv is F and gold.entscheidung is not F


class Metriken(BaseModel):
    model_config = ConfigDict(frozen=True)

    anzahl: int
    kosten_pro_100: Decimal
    kosten_pro_100_real: Decimal  # umgerechnet auf die realistische Fehlerquote
    token_kosten_pro_100: Decimal
    genauigkeit: float  # effektive Entscheidung == Gold
    unsichere_aktionen: int
    rate_unsicher: float
    last_mensch: float  # Anteil effektiv ESKALIEREN
    automatisierung: float  # Anteil ohne Menschen (effektiv FREIGEBEN oder ZURUECKHALTEN)
    interrupt_rate: float
    extraktion_fehler: int
    erkennung_pro_typ: dict[str, float]  # F-Typen: richtige Entscheidung und Typ-Code genannt
    fehlalarm_pro_typ: dict[str, float]  # H-Typen und SAUBER: nicht freigegeben
    latenz_p50_ms: float  # nur über live beantwortete Fälle, falls es welche gibt
    latenz_p95_ms: float
    anteil_cache: float = 0.0  # Anteil der Fälle, deren LLM-Antworten alle aus dem Cache kamen
    nach_layout: dict[str, dict[str, float]] = {}  # A = bekanntes, C = unbekanntes Format


def _gewichte(gold: Sequence[Gold], quote: Decimal) -> list[Decimal]:
    """Gewichte, mit denen der Anteil fehlerhafter Rechnungen der realen Quote entspricht."""
    fehlerhaft = [g.entscheidung is not F for g in gold]
    n_f = sum(fehlerhaft)
    n_ok = len(gold) - n_f
    if n_f == 0 or n_ok == 0:
        return [Decimal(1)] * len(gold)
    w_f = quote / (Decimal(n_f) / len(gold))
    w_ok = (1 - quote) / (Decimal(n_ok) / len(gold))
    return [w_f if f else w_ok for f in fehlerhaft]


def _perzentil(werte: list[float], p: float) -> float:
    if not werte:
        return 0.0
    s = sorted(werte)
    i = min(len(s) - 1, max(0, round(p * (len(s) - 1))))
    return s[i]


def berechne(gold: Sequence[Gold], vorhersagen: Sequence[Vorhersage], k: KostenConfig) -> Metriken:
    nach_id = {v.fall_id: v for v in vorhersagen}
    fehlend = [g.fall_id for g in gold if g.fall_id not in nach_id]
    if fehlend:
        raise ValueError(f"Keine Vorhersage für {len(fehlend)} Fälle, z.B. {fehlend[:3]}")
    paare = [(g, nach_id[g.fall_id]) for g in gold]
    n = len(paare)

    einzel = [kosten(g, v, k) for g, v in paare]
    gewichte = _gewichte(gold, k.fehlerquote_real)
    real = sum((c * w for c, w in zip(einzel, gewichte, strict=True)), Decimal(0))

    erkannt: defaultdict[str, list[bool]] = defaultdict(list)
    fehlalarm: defaultdict[str, list[bool]] = defaultdict(list)
    for g, v in paare:
        if g.entscheidung is F:
            fehlalarm[g.typ].append(v.effektiv is not F)
        elif g.typ in Code.__members__:  # Angriffe (A1-A12) haben keinen Fehlertyp-Code
            erkannt[g.typ].append(v.effektiv == g.entscheidung and Code(g.typ) in v.codes)

    unsicher = sum(ist_unsicher(g, v) for g, v in paare)
    eskaliert = sum(v.effektiv is E for _, v in paare)
    live = [v.latenz_ms for _, v in paare if not v.aus_cache]
    latenzen = live or [v.latenz_ms for _, v in paare]
    nach_layout: dict[str, dict[str, float]] = {}
    for layout in sorted({g.layout for g, _ in paare}):
        teil = [(g, v, c) for (g, v), c in zip(paare, einzel, strict=True) if g.layout == layout]
        m = len(teil)
        nach_layout[layout] = {
            "anzahl": m,
            "kosten_pro_100": float(sum((c for _, _, c in teil), Decimal(0)) * 100 / m),
            "genauigkeit": sum(v.effektiv == g.entscheidung for g, v, _ in teil) / m,
            "rate_unsicher": sum(ist_unsicher(g, v) for g, v, _ in teil) / m,
            "extraktion_fehler": sum(not v.extraktion_ok for _, v, _ in teil),
        }
    return Metriken(
        anzahl=n,
        kosten_pro_100=(sum(einzel, Decimal(0)) * 100 / n).quantize(Decimal("0.01")),
        kosten_pro_100_real=(real * 100 / n).quantize(Decimal("0.01")),
        token_kosten_pro_100=(
            sum((v.kosten_tokens_eur for _, v in paare), Decimal(0)) * 100 / n
        ).quantize(Decimal("0.0001")),
        genauigkeit=sum(v.effektiv == g.entscheidung for g, v in paare) / n,
        unsichere_aktionen=unsicher,
        rate_unsicher=unsicher / n,
        last_mensch=eskaliert / n,
        automatisierung=1 - eskaliert / n,
        interrupt_rate=sum(v.interrupt for _, v in paare) / n,
        extraktion_fehler=sum(not v.extraktion_ok for _, v in paare),
        erkennung_pro_typ={t: sum(w) / len(w) for t, w in sorted(erkannt.items())},
        fehlalarm_pro_typ={t: sum(w) / len(w) for t, w in sorted(fehlalarm.items())},
        latenz_p50_ms=_perzentil(latenzen, 0.50),
        latenz_p95_ms=_perzentil(latenzen, 0.95),
        anteil_cache=sum(v.aus_cache for _, v in paare) / n,
        nach_layout=nach_layout,
    )
