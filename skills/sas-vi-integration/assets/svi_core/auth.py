"""Autenticazione verso SAS Viya (SASLogon) — generica, `cfg`-driven.

Tre modalità (SVI_AUTH_MODE): `oauth` (grant client_credentials|password), `token`
(bearer già ottenuto), `broker` (sidecar). Il token è messo in cache fino a poco prima
della scadenza. `build_oauth_request` è **pura** (nessun I/O) → testabile senza rete.
"""
from __future__ import annotations

import base64
import time
from typing import Any

import httpx

# Cache in-process del token (semplice; in prod valutare cache condivisa/rinnovo proattivo).
_cache: dict[str, Any] = {"token": None, "exp": 0.0}


def build_oauth_request(cfg) -> tuple[str, dict[str, str], dict[str, str]]:
    """Costruisce (url, form-data, headers) per la richiesta token SASLogon.
    Client autenticato via HTTP Basic (client_id:client_secret), come da convenzione."""
    data = {"grant_type": cfg.sas_oauth_grant}
    if cfg.sas_oauth_grant == "password":
        data["username"] = cfg.sas_username
        data["password"] = cfg.sas_password
    if cfg.sas_oauth_scope:
        data["scope"] = cfg.sas_oauth_scope
    basic = base64.b64encode(f"{cfg.sas_client_id}:{cfg.sas_client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    return cfg.token_url(), data, headers


async def _fetch_token(client: httpx.AsyncClient, cfg) -> tuple[str, float]:
    if cfg.svi_auth_mode == "broker":
        resp = await client.get(cfg.sas_token_broker_url, timeout=cfg.svi_request_timeout)
        resp.raise_for_status()
        body = resp.json()
        return body["access_token"], float(body.get("expires_in", 600))
    url, data, headers = build_oauth_request(cfg)
    resp = await client.post(url, data=data, headers=headers, timeout=cfg.svi_request_timeout)
    resp.raise_for_status()
    body = resp.json()
    return body["access_token"], float(body.get("expires_in", 600))


async def bearer(client: httpx.AsyncClient, cfg) -> str:
    """Token valido dalla cache o rinnovato (margine 30 s sulla scadenza)."""
    if cfg.svi_auth_mode == "token":
        if not cfg.sas_bearer_token:
            raise RuntimeError("SVI_AUTH_MODE=token ma SAS_BEARER_TOKEN è vuoto")
        return cfg.sas_bearer_token
    now = time.time()
    if _cache["token"] and now < _cache["exp"]:
        return _cache["token"]
    token, ttl = await _fetch_token(client, cfg)
    _cache["token"] = token
    _cache["exp"] = now + max(0.0, ttl - 30.0)
    return token


def reset_cache() -> None:
    _cache["token"] = None
    _cache["exp"] = 0.0
