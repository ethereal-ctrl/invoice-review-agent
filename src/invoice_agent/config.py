"""Konfiguration aus YAML (Werte gemäß docs/spezifikation.md)."""

from decimal import Decimal
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from invoice_agent.llm.client import LlmProfil


class _Basis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Toleranzen(_Basis):
    preis_prozent: Decimal = Field(ge=0)
    betrag_eur: Decimal = Field(ge=0)
    duplikat_tage: int = Field(gt=0)


class PolicyConfig(_Basis):
    freigabegrenze_eur: Decimal = Field(gt=0)
    fenster_tage: int = Field(gt=0)


class GeneratorConfig(_Basis):
    seed: int
    anzahl: int = Field(gt=0)
    dev: int = Field(gt=0)
    test: int = Field(gt=0)
    smoke: int = Field(gt=0)

    @model_validator(mode="after")
    def _splits_pruefen(self) -> Self:
        if self.dev + self.test != self.anzahl:
            raise ValueError("dev + test muss anzahl ergeben")
        if self.smoke > self.dev:
            raise ValueError("smoke ist eine Teilmenge von dev und darf nicht größer sein")
        return self


class KostenConfig(_Basis):
    zurueckhalten_statt_freigeben: Decimal = Field(ge=0)
    eskalieren_unnoetig: Decimal = Field(ge=0)
    zurueckhalten_statt_eskalieren: Decimal = Field(ge=0)
    fehlerquote_real: Decimal = Field(gt=0, lt=1)
    bootstrap_wiederholungen: int = Field(gt=0)
    bootstrap_seed: int


class LlmConfig(_Basis):
    worker: int = Field(default=4, gt=0)
    cache_dir: Path = Path("cache/llm")
    profile: dict[str, LlmProfil] = {}


class Settings(_Basis):
    toleranzen: Toleranzen
    policy: PolicyConfig
    kosten: KostenConfig
    generator: GeneratorConfig
    llm: LlmConfig = LlmConfig()


def lade(pfad: Path) -> Settings:
    with pfad.open(encoding="utf-8") as f:
        roh = yaml.safe_load(f)
    return Settings.model_validate(roh)
