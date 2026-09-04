"""Fetch conforme (§4.3 del capitolato).

- Rispetto di **robots.txt** (Disallow) e del **crawl-delay** dichiarato.
- **User-Agent** identificabile (con contatto).
- **Rate limiting** per dominio (best-effort in-process; TODO: distribuito su Redis).
- Timeout e follow dei redirect. Nessun aggiramento di paywall/DRM.

Nota: le pagine dinamiche (JS) richiederebbero un headless browser (Playwright):
lasciato come estensione (TODO) per non appesantire l'immagine del worker.
"""
from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "AdverseMediaBot/0.1 (+contatto: esempio@amministrazione.it)",
)
DEFAULT_DELAY = float(os.getenv("SCRAPER_DEFAULT_CRAWL_DELAY", "2.0"))
RESPECT_ROBOTS = os.getenv("SCRAPER_RESPECT_ROBOTS", "true").lower() == "true"
TIMEOUT = float(os.getenv("SCRAPER_TIMEOUT", "20"))

_robots: dict[str, RobotFileParser] = {}
_last_access: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def _host(url: str) -> str:
    return urlparse(url).netloc


async def _get_robots(url: str) -> RobotFileParser:
    parsed = urlparse(url)
    host = parsed.netloc
    if host in _robots:
        return _robots[host]
    rp = RobotFileParser()
    robots_url = f"{parsed.scheme}://{host}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as c:
            r = await c.get(robots_url)
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
        else:
            rp.allow_all = True  # nessun robots.txt → consentito
    except Exception:
        rp.allow_all = True
    _robots[host] = rp
    return rp


async def _throttle(host: str, delay: float) -> None:
    lock = _locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = delay - (time.monotonic() - _last_access.get(host, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _last_access[host] = time.monotonic()


async def fetch(url: str) -> dict:
    """Recupera l'URL rispettando robots/crawl-delay. Non solleva su errori di
    rete: restituisce sempre un esito strutturato (status/allowed/error)."""
    host = _host(url)
    delay = DEFAULT_DELAY
    if RESPECT_ROBOTS:
        rp = await _get_robots(url)
        if not rp.can_fetch(USER_AGENT, url):
            return {"url": url, "allowed": False, "status": None, "body": None,
                    "final_url": url, "content_type": "", "headers": {}, "error": "blocked_by_robots"}
        cd = rp.crawl_delay(USER_AGENT)
        if cd:
            delay = max(delay, float(cd))

    await _throttle(host, delay)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as c:
            r = await c.get(url)
        return {
            "url": url, "allowed": True, "status": r.status_code, "final_url": str(r.url),
            "content_type": r.headers.get("content-type", ""), "body": r.content,
            "headers": dict(r.headers), "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — errore di rete non fatale per la pipeline
        return {"url": url, "allowed": True, "status": None, "body": None, "final_url": url,
                "content_type": "", "headers": {}, "error": f"fetch_error: {exc}"}
