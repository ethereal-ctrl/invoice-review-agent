"""LLM-Client (Cache, Replay, Backoff) und LLM-Extraktion mit einem Fake-Provider."""

import json
import random
from pathlib import Path

import httpx
import pytest

from invoice_agent.config import lade
from invoice_agent.domain import Entscheidung
from invoice_agent.generator.faelle import erzeuge
from invoice_agent.generator.render import render, waehle_variante
from invoice_agent.llm.client import CacheFehlschlag, ChatClient, LlmFehler, LlmProfil
from invoice_agent.model import Rechnung
from invoice_agent.stufen.extraktion import ExtraktionsFehler
from invoice_agent.stufen.llm_extraktion import LlmExtraktion, json_aus_antwort
from invoice_agent.stufen.regeln import llm

CONFIG = Path(__file__).parents[1] / "configs" / "default.yaml"
PROFIL = LlmProfil(provider="fake", basis_url="http://fake/v1", modell="m", rpm=1000)


def _antwort(text: str, status: int = 200) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    return httpx.Response(status, json=body)


class _Fake:
    def __init__(self, antworten: list[httpx.Response]) -> None:
        self.antworten = antworten
        self.aufrufe = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.aufrufe += 1
        return self.antworten.pop(0)


def _client(tmp_path: Path, fake: _Fake, modus: str = "live") -> ChatClient:
    return ChatClient(PROFIL, tmp_path, modus, transport=httpx.MockTransport(fake))  # pyright: ignore[reportArgumentType]


NACHRICHT = [{"role": "user", "content": "hallo"}]


def test_cache_verhindert_zweiten_aufruf(tmp_path: Path) -> None:
    fake = _Fake([_antwort("eins")])
    c = _client(tmp_path, fake)
    assert c.chat(NACHRICHT).text == "eins"
    zweite = c.chat(NACHRICHT)
    assert zweite.text == "eins" and zweite.aus_cache
    assert fake.aufrufe == 1


def test_replay_ohne_cache_ist_fehler(tmp_path: Path) -> None:
    c = _client(tmp_path, _Fake([]), "replay")
    with pytest.raises(CacheFehlschlag):
        c.chat(NACHRICHT)


def test_replay_liest_cache(tmp_path: Path) -> None:
    _client(tmp_path, _Fake([_antwort("gespeichert")])).chat(NACHRICHT)
    assert _client(tmp_path, _Fake([]), "replay").chat(NACHRICHT).text == "gespeichert"


def test_backoff_bei_429(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def nicht_schlafen(_: float) -> None:
        return None

    monkeypatch.setattr("time.sleep", nicht_schlafen)
    fake = _Fake([httpx.Response(429), httpx.Response(503), _antwort("ok")])
    assert _client(tmp_path, fake).chat(NACHRICHT).text == "ok"
    assert fake.aufrufe == 3


def test_kein_retry_bei_400(tmp_path: Path) -> None:
    with pytest.raises(LlmFehler):
        _client(tmp_path, _Fake([httpx.Response(400, text="kaputt")])).chat(NACHRICHT)


def test_fehlender_key_bricht_ab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAKE_KEY", raising=False)
    profil = PROFIL.model_copy(update={"key_env": "FAKE_KEY"})
    with pytest.raises(LlmFehler, match="FAKE_KEY"):
        ChatClient(profil, tmp_path)


def test_json_aus_antwort_entfernt_denken_und_markdown() -> None:
    text = '<think>hmm {"x": 0}</think>\n```json\n{"a": 1}\n```'
    assert json_aus_antwort(text) == {"a": 1}


def test_json_fehlt() -> None:
    with pytest.raises(ExtraktionsFehler):
        json_aus_antwort("kein json")


def _als_llm_json(re: Rechnung) -> str:
    d = re.model_dump(mode="json")
    d.pop("freitext")
    return json.dumps(d)


def test_llm_stufe_mit_perfekter_extraktion(tmp_path: Path) -> None:
    settings = lade(CONFIG)
    ergebnis = erzeuge(settings)
    fall = ergebnis.faelle[0]
    pdf = tmp_path / "re.pdf"
    render(fall.rechnung, pdf, waehle_variante(random.Random(0), "C"))
    fake = _Fake([_antwort(_als_llm_json(fall.rechnung))])
    stufe = llm("llm:fake", settings, ergebnis.welt, LlmExtraktion(_client(tmp_path, fake)))
    v = stufe.entscheide(fall.fall_id, pdf)
    assert v.extraktion_ok
    assert v.effektiv == (Entscheidung.ESKALIEREN if v.interrupt else fall.gold.entscheidung)
    assert set(v.codes) == set(fall.gold.codes)
    assert (v.tokens_ein, v.tokens_aus) == (100, 50)


def test_llm_stufe_eskaliert_bei_unsinn(tmp_path: Path) -> None:
    settings = lade(CONFIG)
    ergebnis = erzeuge(settings)
    fall = ergebnis.faelle[0]
    pdf = tmp_path / "re.pdf"
    render(fall.rechnung, pdf, waehle_variante(random.Random(0)))
    fake = _Fake([_antwort('{"re_nr": "X"}')])
    stufe = llm("llm:fake", settings, ergebnis.welt, LlmExtraktion(_client(tmp_path, fake)))
    v = stufe.entscheide(fall.fall_id, pdf)
    assert not v.extraktion_ok
    assert v.effektiv is Entscheidung.ESKALIEREN
