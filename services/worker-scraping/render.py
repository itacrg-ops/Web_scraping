"""Render headless (Playwright/Chromium) per pagine JS-rendered — fallback B6.

Usato SOLO quando l'estrazione dal fetch HTTP è povera (SPA/contenuti resi in
JavaScript). Ritorna un esito con la STESSA forma di `fetcher.fetch`, così lo
snapshot e l'estrazione a valle (WARC, hash SHA-256, provenance) restano
identici. Non sostituisce il fetch conforme: il render avviene su URL già passati
dal controllo robots.txt/crawl-delay a monte.

L'import di Playwright è **lazy** (dentro `render`): la dipendenza è pesante e il
worker deve poter partire anche dove il fallback è disattivato.
"""
from __future__ import annotations

import os

USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "AdverseMediaBot/0.1 (+contatto: esempio@amministrazione.it)",
)
TIMEOUT_MS = int(float(os.getenv("HEADLESS_TIMEOUT", "20")) * 1000)
# Percorso esplicito del binario Chromium (opzionale): di norma Playwright lo
# risolve da PLAYWRIGHT_BROWSERS_PATH impostato nell'immagine.
_EXECUTABLE = os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or None


def _empty(url: str, error: str) -> dict:
    return {"url": url, "allowed": True, "status": None, "final_url": url,
            "content_type": "", "body": None, "headers": {}, "error": error}


async def render(url: str) -> dict:
    """Rende la pagina con Chromium headless e ritorna l'HTML del DOM finale
    (stessa forma di `fetcher.fetch`). Non solleva: su dipendenza mancante,
    timeout o errore ritorna un esito con `body=None` ed `error` valorizzato."""
    try:
        # import lazy dentro il try: se Playwright non è installato, degradiamo
        # con un errore invece di far fallire l'attività.
        from playwright.async_api import TimeoutError as PWTimeout  # noqa: PLC0415
        from playwright.async_api import async_playwright  # noqa: PLC0415

        async with async_playwright() as p:
            launch: dict = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
            if _EXECUTABLE:
                launch["executable_path"] = _EXECUTABLE
            browser = await p.chromium.launch(**launch)
            try:
                ctx = await browser.new_context(user_agent=USER_AGENT)
                page = await ctx.new_page()
                resp = None
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                    # Dà tempo al JS di popolare il DOM; tollera il polling continuo.
                    try:
                        await page.wait_for_load_state("networkidle", timeout=min(TIMEOUT_MS, 8000))
                    except PWTimeout:
                        pass
                except PWTimeout:
                    pass  # navigazione lenta: proviamo comunque a leggere il DOM parziale
                html = await page.content()
                final_url = page.url
                status = resp.status if resp else 200
                ctype = (resp.headers.get("content-type") if resp else "") or "text/html; charset=utf-8"
                headers = dict(resp.headers) if resp else {}
            finally:
                await browser.close()
        if not html:
            return _empty(url, "render_vuoto")
        return {"url": url, "allowed": True, "status": status, "final_url": final_url,
                "content_type": ctype, "body": html.encode("utf-8"), "headers": headers, "error": None}
    except Exception as exc:  # noqa: BLE001 — dipendenza/timeout/crash: non fatale
        return _empty(url, f"render_error: {type(exc).__name__}: {exc}")
