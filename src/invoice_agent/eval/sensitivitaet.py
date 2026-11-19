"""Sensitivität der Kostenmatrix (ADR 0006): Hält die Reihenfolge der Stufen, wenn die
angenommenen Pauschalen halbiert oder verdoppelt werden, oder die reale Fehlerquote anders ist?

Variiert werden nur die Annahmen. Die Beträge, die bei falscher Freigabe zu viel gezahlt
werden, sind keine Annahme und bleiben fest.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from invoice_agent.config import KostenConfig
from invoice_agent.eval.metriken import Vorhersage, berechne
from invoice_agent.gold import Gold

FAKTOREN = (Decimal("0.5"), Decimal("1"), Decimal("2"))
FEHLERQUOTEN = (Decimal("0.02"), Decimal("0.05"), Decimal("0.10"))


@dataclass(frozen=True)
class Szenario:
    name: str
    kosten: dict[str, Decimal]  # Stufe -> Kosten pro 100 bei realer Fehlerquote
    reihenfolge: tuple[tuple[str, ...], ...]  # günstigste zuerst; gleiche Kosten = eine Gruppe

    @property
    def rangfolge(self) -> str:
        return " < ".join(" = ".join(gruppe) for gruppe in self.reihenfolge)


def _skaliert(k: KostenConfig, faktor: Decimal, quote: Decimal) -> KostenConfig:
    return k.model_copy(
        update={
            "zurueckhalten_statt_freigeben": k.zurueckhalten_statt_freigeben * faktor,
            "eskalieren_unnoetig": k.eskalieren_unnoetig * faktor,
            "zurueckhalten_statt_eskalieren": k.zurueckhalten_statt_eskalieren * faktor,
            "fehlerquote_real": quote,
        }
    )


def analysiere(
    gold: Sequence[Gold], laeufe: Mapping[str, Sequence[Vorhersage]], k: KostenConfig
) -> list[Szenario]:
    szenarien: list[Szenario] = []
    for quote in FEHLERQUOTEN:
        for faktor in FAKTOREN:
            kk = _skaliert(k, faktor, quote)
            kosten = {s: berechne(gold, v, kk).kosten_pro_100_real for s, v in laeufe.items()}
            werte = sorted(set(kosten.values()))
            reihenfolge = tuple(tuple(sorted(s for s in kosten if kosten[s] == w)) for w in werte)
            name = f"Pauschalen x{faktor}, Fehlerquote {quote * 100:.0f} %"
            szenarien.append(Szenario(name, kosten, reihenfolge))
    return szenarien
