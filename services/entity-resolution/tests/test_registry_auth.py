"""Test del client del registro soggetti (endpoint interno dell'API).

- invia il token di servizio `X-Internal-Token` quando configurato;
- se l'API rifiuta/non risponde e non c'è cache: seed demo SOLO in development,
  altrimenti registro vuoto (nessun confronto di soggetti reali con dati demo).

    python services/entity-resolution/tests/test_registry_auth.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import registry  # noqa: E402
from app.config import settings  # noqa: E402


class _Resp:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code, self._body = status, body or {}

    def json(self) -> dict:
        return self._body


def _with(fake_get, *, token: str = "", env: str = "development") -> list[dict]:
    saved = (registry.httpx.get, settings.internal_api_token, settings.app_env)
    registry.httpx.get = fake_get
    settings.internal_api_token, settings.app_env = token, env
    registry._cache.update(ts=0.0, data=None)
    try:
        return registry.get_registry()
    finally:
        registry.httpx.get, settings.internal_api_token, settings.app_env = saved
        registry._cache.update(ts=0.0, data=None)


def test_sends_internal_token() -> None:
    seen: dict = {}

    def fake_get(url, headers=None, timeout=None):
        seen["headers"] = headers
        return _Resp(200, {"subjects": [{"id": "X"}]})

    assert _with(fake_get, token="tok") == [{"id": "X"}]
    assert seen["headers"] == {"X-Internal-Token": "tok"}
    _with(fake_get, token="")
    assert seen["headers"] is None                      # nessun header se non configurato


def test_rejected_without_cache_uses_demo_seed_only_in_development() -> None:
    def rejected(url, headers=None, timeout=None):
        return _Resp(401)

    assert _with(rejected, env="development") == registry._FALLBACK
    assert _with(rejected, env="production") == []


def test_unreachable_without_cache_is_empty_outside_development() -> None:
    def down(url, headers=None, timeout=None):
        raise ConnectionError("api giù")

    assert _with(down, env="production") == []


def test_fresh_reads_again_despite_the_cache() -> None:
    calls: list[int] = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(1)
        return _Resp(200, {"subjects": [{"id": f"X{len(calls)}"}]})

    saved = registry.httpx.get
    registry.httpx.get = fake_get
    registry._cache.update(ts=0.0, data=None)
    try:
        assert registry.get_registry() == [{"id": "X1"}]
        assert registry.get_registry() == [{"id": "X1"}]              # dalla cache
        assert registry.get_registry(fresh=True) == [{"id": "X2"}]    # riletto subito
    finally:
        registry.httpx.get = saved
        registry._cache.update(ts=0.0, data=None)
    assert len(calls) == 2


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
