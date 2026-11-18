"""Gepaarter Bootstrap: Differenz zweier Läufe auf denselben Fällen mit 95-%-Intervall."""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from invoice_agent.config import KostenConfig
from invoice_agent.eval.metriken import E, Vorhersage, ist_unsicher, kosten
from invoice_agent.gold import Gold

Kennzahl = Callable[[Gold, Vorhersage], float]


@dataclass(frozen=True)
class Vergleich:
    kennzahl: str
    a: float
    b: float
    differenz: float  # b - a
    unten: float
    oben: float

    @property
    def signifikant(self) -> bool:
        return self.unten > 0 or self.oben < 0


def kennzahlen(k: KostenConfig) -> dict[str, Kennzahl]:
    return {
        "kosten_pro_100": lambda g, v: float(kosten(g, v, k)) * 100,
        "genauigkeit": lambda g, v: float(v.effektiv == g.entscheidung),
        "rate_unsicher": lambda g, v: float(ist_unsicher(g, v)),
        "last_mensch": lambda g, v: float(v.effektiv is E),
    }


def vergleiche(
    gold: Sequence[Gold],
    a: Sequence[Vorhersage],
    b: Sequence[Vorhersage],
    k: KostenConfig,
) -> list[Vergleich]:
    """Vergleicht Lauf b mit Lauf a. Beide müssen alle Fälle in `gold` enthalten."""
    va = {v.fall_id: v for v in a}
    vb = {v.fall_id: v for v in b}
    paare = [(g, va[g.fall_id], vb[g.fall_id]) for g in gold]
    n = len(paare)
    rng = random.Random(k.bootstrap_seed)
    stichproben = [[rng.randrange(n) for _ in range(n)] for _ in range(k.bootstrap_wiederholungen)]

    ergebnis: list[Vergleich] = []
    for name, f in kennzahlen(k).items():
        werte_a = [f(g, x) for g, x, _ in paare]
        werte_b = [f(g, y) for g, _, y in paare]
        diffs = [wb - wa for wa, wb in zip(werte_a, werte_b, strict=True)]
        boot = sorted(sum(diffs[i] for i in s) / n for s in stichproben)
        ergebnis.append(
            Vergleich(
                kennzahl=name,
                a=sum(werte_a) / n,
                b=sum(werte_b) / n,
                differenz=sum(diffs) / n,
                unten=boot[int(0.025 * len(boot))],
                oben=boot[min(len(boot) - 1, int(0.975 * len(boot)))],
            )
        )
    return ergebnis
