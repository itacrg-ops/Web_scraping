"""Estrazione contenuti: boilerplate removal + testo/metadati (trafilatura).

Funzione sincrona/CPU-bound: invocare da attività async via `asyncio.to_thread`.
"""
from __future__ import annotations

import trafilatura


def extract(html: str, url: str | None = None) -> dict:
    text = trafilatura.extract(
        html or "", url=url, include_comments=False, favor_recall=True
    ) or ""
    title = date = author = None
    try:
        md = trafilatura.extract_metadata(html or "", default_url=url)
        if md is not None:
            title, date, author = md.title, md.date, md.author
    except Exception:
        pass
    return {"text": text, "title": title, "date": date, "author": author}
