"""Autenticazione verso SAS Viya per il publisher SVI (solo modalità "live").

Due modalità:
  - "oauth"  : OAuth2 su SASLogon ({viya}/SASLogon/oauth/token), grant
               client_credentials (default) o password;
  - "broker" : token di servizio ottenuto da un sidecar (sas-token-broker).

Il token viene messo in cache fino a poco prima della scadenza. La costruzione
della richiesta OAuth è isolata in una funzione **pura** (`build_oauth_request`),
così è testabile senza rete.
"""
from __future__ import annotations

import base64
import time
from typing import Any

import httpx

from app.config import settings

# Cache in-process del token (semplice; in prod: cache condivisa/rinnovo proattivo).
_cache: dict[str, Any] = {"token": None, "exp": 0.0}


def build_oauth_request(cfg) -> tuple[str, dict[str, str], dict[str, str]]:
    """Costruisce (url, form-data, headers) per la richiesta token SASLogon.

    Autenticazione del client via HTTP Basic (client_id:client_secret), come da
    convenzione SASLogon. Ritorna dati pronti per un POST x-www-form-urlencoded.
    """
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


async def _fetch_token(client: httpx.AsyncClient) -> tuple[str, float]:
    """Ritorna (access_token, secondi_di_validità)."""
    if settings.svi_auth_mode == "broker":
        resp = await client.get(settings.sas_token_broker_url, timeout=settings.svi_request_timeout)
        resp.raise_for_status()
        body = resp.json()
        return body["access_token"], float(body.get("expires_in", 600))

    url, data, headers = build_oauth_request(settings)
    resp = await client.post(url, data=data, headers=headers, timeout=settings.svi_request_timeout)
    resp.raise_for_status()
    body = resp.json()
    return body["access_token"], float(body.get("expires_in", 600))


async def bearer(client: httpx.AsyncClient) -> str:
    """Token valido dalla cache o rinnovato (margine di 30s sulla scadenza)."""
    now = time.time()
    if _cache["token"] and now < _cache["exp"]:
        return _cache["token"]
    token, ttl = await _fetch_token(client)
    _cache["token"] = token
    _cache["exp"] = now + max(0.0, ttl - 30.0)
    return token


def reset_cache() -> None:
    """Invalida la cache del token (test / rotazione forzata)."""
    _cache["token"] = None
    _cache["exp"] = 0.0
