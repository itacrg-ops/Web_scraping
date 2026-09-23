"""Autenticazione / autorizzazione.

- `auth_mode = disabled` (dev): utente fittizio, nessun controllo.
- `auth_mode = entra`: valida il Bearer JWT emesso da Entra ID (MSAL) —
  firma (JWKS RS256), audience e issuer — ed estrae nome e ruoli (app roles).

L'API è l'**unico confine di fiducia** verso la console (§3 deployment):
autentica, autorizza (RBAC via ruoli), e scrive l'audit.
"""
from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass, field
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException, Request
from jwt import PyJWKClient

from app.config import settings

logger = logging.getLogger("api.auth")


@dataclass
class User:
    name: str
    roles: list[str] = field(default_factory=list)
    sub: str | None = None


_DEV_USER = User(name="Sviluppatore (dev)", roles=["amministratore", "auditor"], sub="dev")


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    uri = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/discovery/v2.0/keys"
    return PyJWKClient(uri)


def _valid_issuers() -> set[str]:
    t = settings.entra_tenant_id
    return {
        f"https://login.microsoftonline.com/{t}/v2.0",
        f"https://sts.windows.net/{t}/",
    }


async def require_user(request: Request) -> User:
    if settings.auth_mode != "entra":
        return _DEV_USER

    authz = request.headers.get("authorization", "")
    if not authz.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="token mancante")
    token = authz.split(" ", 1)[1]
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token, signing_key.key, algorithms=["RS256"],
            audience=settings.entra_api_audience,
        )
    except Exception as exc:  # noqa: BLE001 — token non valido/scaduto/firma
        raise HTTPException(status_code=401, detail=f"token non valido: {exc}") from exc

    if claims.get("iss") not in _valid_issuers():
        raise HTTPException(status_code=401, detail="issuer non atteso")

    name = claims.get("name") or claims.get("preferred_username") or claims.get("upn") or "utente"
    roles = claims.get("roles") or []
    return User(name=name, roles=list(roles), sub=claims.get("sub"))


def check_roles(user: User, roles: list[str]) -> None:
    """403 se l'utente non ha ALMENO uno dei ruoli (app roles di Entra). In dev (auth
    disabilitata) l'utente fittizio ha i ruoli amministrativi."""
    if not set(roles) & set(user.roles):
        raise HTTPException(status_code=403, detail=f"serve uno dei ruoli: {', '.join(roles)}")


async def require_internal(x_internal_token: str | None = Header(default=None)) -> None:
    """Protegge gli endpoint interni service-to-service (worker/entity-resolution → API).

    - `INTERNAL_API_TOKEN` configurato → serve l'header `X-Internal-Token` identico
      (confronto a tempo costante).
    - Token NON configurato → aperto SOLO con `APP_ENV=development`; in ogni altro
      ambiente l'endpoint resta chiuso (fail-closed): un deploy dimenticato senza
      token non espone il registro soggetti né la scrittura degli alert.
    """
    expected = settings.internal_api_token
    if not expected:
        if settings.app_env == "development":
            return
        logger.error("INTERNAL_API_TOKEN non configurato con APP_ENV=%s: endpoint interno chiuso",
                     settings.app_env)
        raise HTTPException(status_code=503, detail="endpoint interno non configurato")
    if not x_internal_token or not hmac.compare_digest(x_internal_token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="token interno non valido")
