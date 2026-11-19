"""Chat-Client für OpenAI-kompatible Endpunkte (NVIDIA NIM, Gemini, Ollama).

- Antwort-Cache auf der Platte, getrennt nach Provider (Namespace), Schlüssel = Hash der Anfrage
- Modus `replay`: nur aus dem Cache, ein Cache-Fehlschlag ist ein Fehler (CI, ADR 0007)
- Rate Limiter (Anfragen pro Minute) und Backoff bei 429/5xx
- Ein Provider pro Lauf: Ein Client gehört genau zu einem Profil
"""

import hashlib
import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

Modus = Literal["live", "replay"]


class LlmProfil(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str  # nur Namespace und Anzeige
    basis_url: str
    modell: str
    key_env: str | None = None  # Name der Umgebungsvariable mit dem API-Key
    rpm: int = Field(default=30, gt=0)
    timeout_s: float = Field(default=120.0, gt=0)
    max_versuche: int = Field(default=6, gt=0)
    temperatur: float = 0.0
    max_tokens: int = Field(default=2048, gt=0)
    preis_ein_pro_mio: Decimal = Decimal(0)  # notionell, für die Kostenrechnung
    preis_aus_pro_mio: Decimal = Decimal(0)
    extra_body: dict[str, object] = {}  # z.B. {"think": false} für Ollama


class _Nachricht(BaseModel):
    content: str | None = None


class _Wahl(BaseModel):
    message: _Nachricht


class _Verbrauch(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _ChatAntwort(BaseModel):
    choices: list[_Wahl]
    usage: _Verbrauch = _Verbrauch()


class LlmFehler(RuntimeError):
    pass


class CacheFehlschlag(LlmFehler):
    pass


@dataclass(frozen=True)
class Antwort:
    text: str
    tokens_ein: int
    tokens_aus: int
    aus_cache: bool
    latenz_ms: float

    def kosten_eur(self, p: LlmProfil) -> Decimal:
        return (
            Decimal(self.tokens_ein) * p.preis_ein_pro_mio
            + Decimal(self.tokens_aus) * p.preis_aus_pro_mio
        ) / Decimal(1_000_000)


class _RateLimiter:
    def __init__(self, rpm: int) -> None:
        self._rpm = rpm
        self._zeiten: deque[float] = deque()
        self._lock = threading.Lock()

    def warte(self) -> None:
        while True:
            with self._lock:
                jetzt = time.monotonic()
                while self._zeiten and jetzt - self._zeiten[0] > 60:
                    self._zeiten.popleft()
                if len(self._zeiten) < self._rpm:
                    self._zeiten.append(jetzt)
                    return
                warten = 60 - (jetzt - self._zeiten[0]) + 0.05
            time.sleep(warten)


class ChatClient:
    def __init__(
        self,
        profil: LlmProfil,
        cache_dir: Path,
        modus: Modus = "live",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.profil = profil
        self._modus = modus
        self._cache = cache_dir / profil.provider
        self._cache.mkdir(parents=True, exist_ok=True)
        self._limiter = _RateLimiter(profil.rpm)
        headers = {"Content-Type": "application/json"}
        if modus == "live" and profil.key_env:
            key = os.environ.get(profil.key_env)
            if not key:
                raise LlmFehler(f"Umgebungsvariable {profil.key_env} ist nicht gesetzt")
            headers["Authorization"] = f"Bearer {key}"
        self._http = httpx.Client(
            base_url=profil.basis_url.rstrip("/") + "/",
            headers=headers,
            timeout=profil.timeout_s,
            transport=transport,
        )

    def _anfrage(self, nachrichten: list[dict[str, str]]) -> dict[str, object]:
        p = self.profil
        return {
            "model": p.modell,
            "messages": nachrichten,
            "temperature": p.temperatur,
            "max_tokens": p.max_tokens,
            **p.extra_body,
        }

    @staticmethod
    def _schluessel(anfrage: dict[str, object]) -> str:
        roh = json.dumps(anfrage, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(roh.encode("utf-8")).hexdigest()

    def chat(self, nachrichten: list[dict[str, str]]) -> Antwort:
        anfrage = self._anfrage(nachrichten)
        pfad = self._cache / f"{self._schluessel(anfrage)}.json"
        if pfad.exists():
            daten = json.loads(pfad.read_text(encoding="utf-8"))
            return Antwort(daten["text"], daten["tokens_ein"], daten["tokens_aus"], True, 0.0)
        if self._modus == "replay":
            raise CacheFehlschlag(f"Kein Cache-Eintrag für {pfad.name} (Replay-Modus)")

        start = time.perf_counter()
        daten = self._mit_backoff(anfrage)
        latenz = (time.perf_counter() - start) * 1000
        try:
            antwort = _ChatAntwort.model_validate(daten)
            text = antwort.choices[0].message.content or ""
        except (ValidationError, IndexError) as e:
            raise LlmFehler(f"Unerwartete Antwort: {str(daten)[:200]}") from e
        ein, aus = antwort.usage.prompt_tokens, antwort.usage.completion_tokens
        eintrag = {"text": text, "tokens_ein": ein, "tokens_aus": aus, "modell": self.profil.modell}
        tmp = pfad.with_suffix(".tmp")
        tmp.write_text(json.dumps(eintrag, ensure_ascii=False), encoding="utf-8")
        tmp.replace(pfad)  # atomar, damit abgebrochene Läufe keinen halben Eintrag hinterlassen
        return Antwort(text, ein, aus, False, latenz)

    def _mit_backoff(self, anfrage: dict[str, object]) -> dict[str, object]:
        letzter: str = ""
        for versuch in range(self.profil.max_versuche):
            self._limiter.warte()
            try:
                r = self._http.post("chat/completions", json=anfrage)
            except httpx.TransportError as e:
                letzter = f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200:
                    ergebnis: dict[str, object] = r.json()
                    return ergebnis
                letzter = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code not in (408, 429) and r.status_code < 500:
                    raise LlmFehler(letzter)
            time.sleep(min(60.0, 2.0 * 2**versuch))
        raise LlmFehler(f"Nach {self.profil.max_versuche} Versuchen: {letzter}")
