"""Provider di ricerca (astrazione con più backend).

- `mock` (default): risultati deterministici, nessuna rete. Serve allo sviluppo
  locale e all'anteprima in console senza dipendenze esterne.
- `gdelt`: GDELT DOC 2.0 API (news globale, **keyless**), ma rate-limited/instabile.
- `brave`: Brave Search API (news, **a chiave**), affidabile per il pilota.

Altri provider (SerpAPI/Google CSE, o feed licenziati tipo Dow Jones/Factiva) si
aggiungono qui implementando la stessa firma (ritorna (risultati, query, note)).
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app import query as qb
from app.config import settings

logger = logging.getLogger("search-gateway.providers")

# Throttle in-process delle chiamate GDELT (best-effort, singolo worker): GDELT
# limita a ~1 richiesta ogni pochi secondi per IP e risponde 429 se si eccede.
_gdelt_lock = asyncio.Lock()
_gdelt_last = 0.0

# Throttle in-process delle chiamate Brave: la scala di fallback può fare più
# richieste consecutive e il piano free è ~1 query/secondo.
_brave_lock = asyncio.Lock()
_brave_last = 0.0


def _is_person(subject: dict) -> bool:
    return (subject.get("tipo_soggetto") or "persona_giuridica") == "persona_fisica"


def _broadened_note(used_query: str, subject: dict) -> str | None:
    """Nota per la console quando la query vincente ha PERSO i qualificatori
    (azienda/località): la ricerca si è allargata al solo nome. Avvisa che è la
    conferma di azienda/località nel testo degli articoli (anti-omonimia a valle,
    nei driver) a distinguere il soggetto dagli omonimi."""
    if not _is_person(subject):
        return None
    quals = [(subject.get("azienda") or "").strip(), (subject.get("localita") or "").strip()]
    quals = [q for q in quals if q]
    if not quals:
        return None
    if any(f'"{q}"' in used_query for q in quals):
        return None  # almeno un qualificatore è ancora presente nella query vincente
    return ("Nessun articolo con i qualificatori azienda/località: ricerca allargata al "
            "solo nome. La conferma di azienda/località nel testo degli articoli distingue "
            "il soggetto dagli omonimi (vedi i driver dello screening).")


def _result(url, title=None, snippet=None, testata=None, data=None,
            language=None, provider="mock", score=None) -> dict:
    return {
        "url": url, "title": title, "snippet": snippet, "testata": testata,
        "data": data, "language": language, "provider": provider, "score": score,
    }


# --- Provider mock: fixtures deterministiche -------------------------------
# Domini .example distinti + un duplicato (per mostrare la dedup) + una testata
# a bassa credibilità (per mostrare il filtro). Vedi testate.py per i livelli.
_MOCK_ENTRIES = [
    ("ilmessaggero.example", "Il Messaggero (esempio)",
     "Inchiesta appalti: perquisizioni e indagati, coinvolto {name}", "2026-03-26"),
    ("larepubblica.example", "la Repubblica (esempio)",
     "Corruzione e turbativa d'asta: {name} tra i nomi nel fascicolo", "2026-02-14"),
    ("ansa.example", "ANSA (esempio)",
     "Sequestro e accuse di frode: verifiche in corso su {name}", "2025-12-03"),
    # stesso dominio del primo → dev'essere rimosso dalla dedup per dominio
    ("ilmessaggero.example", "Il Messaggero (esempio)",
     "Appalti pubblici, nuovo capitolo dell'inchiesta su {name}", "2026-01-10"),
    # bassa credibilità → rimosso se min_credibility >= media
    ("blognotizie.example", "BlogNotizie (esempio)",
     "Rumors e indiscrezioni non verificate su {name}", "2026-03-01"),
]


def _mock(subject: dict, mode: str, max_results: int) -> list[dict]:
    names = qb.name_variants(subject)
    if not names:
        return []
    display = names[0]
    slug = display.lower().replace(" ", "-").replace("'", "")
    out: list[dict] = []
    for i, (domain, testata, title, date) in enumerate(_MOCK_ENTRIES):
        out.append(_result(
            url=f"https://{domain}/adverse-media/{slug}-{i + 1}",
            title=title.format(name=display),
            snippet=(f"Secondo fonti giudiziarie, {display} risulterebbe coinvolto in "
                     f"un'inchiesta su appalti pubblici (contenuto di esempio, provider mock)."),
            testata=testata, data=date,
            language="Italian", provider="mock", score=round(1.0 - i * 0.1, 2),
        ))
    return out[:max_results]


# --- Provider GDELT DOC 2.0 (keyless) --------------------------------------
def _fmt_gdelt_date(seendate: str | None) -> str | None:
    # GDELT seendate: "YYYYMMDDTHHMMSSZ" -> "YYYY-MM-DD"
    if not seendate or len(seendate) < 8:
        return None
    return f"{seendate[0:4]}-{seendate[4:6]}-{seendate[6:8]}"


async def _throttle_gdelt() -> None:
    """Distanzia le chiamate GDELT di almeno gdelt_min_interval secondi."""
    global _gdelt_last
    async with _gdelt_lock:
        wait = settings.gdelt_min_interval - (time.monotonic() - _gdelt_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _gdelt_last = time.monotonic()


async def _gdelt_call(query_str: str, max_results: int, timespan: str) -> tuple[str, object]:
    """Una singola chiamata GDELT. Ritorna:
      ("ok", list)            articoli (anche [] = nessun risultato);
      ("rate_limited", wait)  429, wait = Retry-After in secondi o None;
      ("error", None)         altro errore (status/parsing/rete)."""
    params = {
        "query": query_str, "mode": "ArtList", "format": "json",
        "maxrecords": str(max(1, min(max_results, 250))),
        "sort": "DateDesc", "timespan": timespan,
    }
    await _throttle_gdelt()
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout,
                                     headers={"User-Agent": settings.gdelt_user_agent}) as c:
            r = await c.get(settings.gdelt_endpoint, params=params)
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            wait = float(ra) if (ra and ra.isdigit()) else None
            logger.warning("GDELT 429 (rate limit) per query=%r retry_after=%s", query_str, ra)
            return "rate_limited", wait
        if r.status_code != 200:
            logger.warning("GDELT status %s per query=%r", r.status_code, query_str)
            return "error", None
        try:
            data = r.json()
        except Exception:  # noqa: BLE001 — GDELT risponde HTML su query invalide
            logger.warning("GDELT: risposta non-JSON (query rifiutata?) query=%r", query_str)
            return "error", None
    except Exception as exc:  # noqa: BLE001 — rete non fatale
        logger.warning("GDELT non raggiungibile: %s: %s", type(exc).__name__, exc)
        return "error", None

    out: list[dict] = []
    for a in (data.get("articles") or []):
        url = a.get("url") or a.get("url_mobile")
        if not url:
            continue
        out.append(_result(
            url=url, title=a.get("title"), snippet=None,
            testata=a.get("domain"), data=_fmt_gdelt_date(a.get("seendate")),
            language=a.get("language"), provider="gdelt", score=None,
        ))
    return "ok", out


async def _gdelt(subject: dict, mode: str, max_results: int, lang: str,
                 timespan: str) -> tuple[list[dict], str, str | None]:
    """Scala di fallback (dalla query più precisa alla più larga) per non restare
    a 0: prova nome+qualificatori/avversi, poi allarga fino al solo nome, infine
    ritenta senza vincolo di lingua. Prosegue alla variante successiva SOLO se la
    precedente è andata a buon fine ma senza articoli; su 429/errore si ferma (un
    solo ciclo di retry sul 429) per non peggiorare il rate limit.
    Ritorna (risultati, query_usata, note)."""
    qvars = qb.build_query_variants(subject, mode)
    if not qvars:
        return [], "", None

    def _with_lang(q: str) -> str:
        return f"{q} sourcelang:{lang}" if lang else q

    variants = [_with_lang(q) for q in qvars]
    if lang:
        variants.append(qvars[-1])  # ultimo tentativo: la più larga senza vincolo di lingua
    _seen: set[str] = set()
    variants = [v for v in variants if not (v in _seen or _seen.add(v))]

    for vq in variants:
        status, payload = await _gdelt_call(vq, max_results, timespan)
        if status == "ok":
            if payload:
                return payload, vq, _broadened_note(vq, subject)
            continue  # ok ma nessun articolo → prova la variante successiva
        if status == "rate_limited":
            retry_after = payload  # secondi dal 429 (o None)
            result = None
            for attempt in range(1, settings.gdelt_retries + 1):
                wait = min(retry_after or settings.gdelt_retry_wait * attempt, settings.gdelt_max_wait)
                await asyncio.sleep(wait)
                st, pl = await _gdelt_call(vq, max_results, timespan)
                if st == "ok":
                    result = pl
                    break
                if st == "error":
                    break
                retry_after = pl  # ancora 429: aggiorna eventuale Retry-After
            if result:
                return result, vq, _broadened_note(vq, subject)
            return [], vq, ("GDELT ha limitato le richieste (429). Attendi qualche "
                            "secondo e riprova, oppure dirada le ricerche.")
        return [], vq, "GDELT non raggiungibile o query rifiutata. Riprova più tardi."
    return [], variants[-1], None


# --- Provider Brave Search (a chiave, affidabile) --------------------------
def _brave_date(a: dict) -> str | None:
    pa = a.get("page_age") or a.get("age")
    if pa and len(pa) >= 10 and pa[4] == "-" and pa[7] == "-":
        return pa[:10]  # ISO -> YYYY-MM-DD
    return pa  # es. "2 days ago" (relativo)


def _brave_items(data: dict) -> list[dict]:
    """Estrae i risultati sia dall'endpoint web che da quello news."""
    return (
        (data.get("web") or {}).get("results")
        or data.get("results")
        or (data.get("news") or {}).get("results")
        or []
    )


async def _throttle_brave() -> None:
    """Distanzia le chiamate Brave di almeno brave_min_interval secondi."""
    global _brave_last
    async with _brave_lock:
        wait = settings.brave_min_interval - (time.monotonic() - _brave_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _brave_last = time.monotonic()


async def _brave_call(query_str: str, max_results: int) -> tuple[str, object]:
    """Una singola chiamata Brave. Ritorna:
      ("ok", list)     risultati (anche [] = nessun risultato);
      ("error", note)  errore da propagare (chiave/parametri/rete)."""
    # NB: country/search_lang vogliono CODICI (it), non nomi lingua. count web: max 20.
    params = {
        "q": query_str,
        "country": settings.brave_country,
        "search_lang": settings.brave_search_lang,
        "count": max(1, min(max_results, 20)),
    }
    headers = {
        "Accept": "application/json", "Accept-Encoding": "gzip",
        "X-Subscription-Token": settings.brave_api_key,
    }
    await _throttle_brave()
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as c:
            r = await c.get(settings.brave_endpoint, params=params, headers=headers)
        if r.status_code != 200:
            body = r.text[:200].replace("\n", " ")
            logger.warning("Brave status %s body=%r", r.status_code, body)
            if r.status_code in (401, 403):
                note = "Brave: chiave non valida o non autorizzata (controlla BRAVE_API_KEY)."
            elif r.status_code == 422:
                note = "Brave: parametri non accettati (422). Verifica country/search_lang (codici, es. it)."
            elif r.status_code == 429:
                note = "Brave ha limitato le richieste (429). Riprova tra poco."
            else:
                note = f"Brave ha risposto {r.status_code}. Riprova più tardi."
            return "error", note
        data = r.json()
    except Exception as exc:  # noqa: BLE001 — rete non fatale
        logger.warning("Brave non raggiungibile: %s: %s", type(exc).__name__, exc)
        return "error", f"Brave non raggiungibile ({type(exc).__name__}). Riprova più tardi."

    out: list[dict] = []
    for a in _brave_items(data):
        url = a.get("url")
        if not url:
            continue
        out.append(_result(
            url=url, title=a.get("title"), snippet=a.get("description"),
            testata=(a.get("meta_url") or {}).get("hostname"),
            data=_brave_date(a), language=None, provider="brave", score=None,
        ))
    return "ok", out


async def _brave(subject: dict, mode: str, max_results: int, lang: str,
                 timespan: str) -> tuple[list[dict], str, str | None]:
    """Scala di fallback come GDELT: prova la query più precisa (nome +
    qualificatori), poi allarga fino al solo nome, fermandosi alla prima con
    risultati. Su errore (chiave/parametri/rete) non insiste."""
    if not settings.brave_api_key:
        return [], "", "Brave non configurato: imposta BRAVE_API_KEY nel .env."
    # Brave/Google: sintassi "plain" (niente parentesi/OR — ogni frase quotata è AND).
    qvars = qb.build_query_variants(subject, mode, syntax="plain")
    if not qvars:
        return [], "", None
    last_q = qvars[0]
    for q in qvars:
        last_q = q
        status, payload = await _brave_call(q, max_results)
        if status == "error":
            return [], q, payload  # chiave/parametri/rete: inutile allargare
        if payload:
            return payload, q, _broadened_note(q, subject)
        # 200 ma nessun risultato → prova la variante più larga
    return [], last_q, _broadened_note(last_q, subject)


# --- Provider SearXNG (meta-search self-hosted, keyless) -------------------
async def _searxng_call(query_str: str, max_results: int) -> tuple[str, object]:
    """Una chiamata all'API JSON di SearXNG. ("ok", list) | ("error", note)."""
    params = {"q": query_str, "format": "json",
              "language": settings.searxng_language, "categories": "news"}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as c:
            r = await c.get(f"{settings.searxng_url.rstrip('/')}/search", params=params)
        if r.status_code != 200:
            note = f"SearXNG ha risposto {r.status_code}."
            if r.status_code in (403, 429):
                note += " Abilita il formato JSON in searxng/settings.yml (formats: [html, json])."
            return "error", note
        data = r.json()
    except Exception as exc:  # noqa: BLE001 — rete non fatale
        logger.warning("SearXNG non raggiungibile: %s: %s", type(exc).__name__, exc)
        return "error", f"SearXNG non raggiungibile ({type(exc).__name__})."
    out: list[dict] = []
    for a in (data.get("results") or []):
        url = a.get("url")
        if not url:
            continue
        pub = (a.get("publishedDate") or "")[:10] or None
        out.append(_result(url=url, title=a.get("title"), snippet=a.get("content"),
                           testata=None, data=pub, language=None,
                           provider="searxng", score=a.get("score")))
        if len(out) >= max_results:
            break
    return "ok", out


async def _searxng(subject: dict, mode: str, max_results: int, lang: str,
                   timespan: str) -> tuple[list[dict], str, str | None]:
    """Scala di fallback come Brave (sintassi plain). SearXNG aggrega più motori:
    niente chiave, niente rate-limit centralizzato."""
    qvars = qb.build_query_variants(subject, mode, syntax="plain")
    if not qvars:
        return [], "", None
    last_q = qvars[0]
    for q in qvars:
        last_q = q
        status, payload = await _searxng_call(q, max_results)
        if status == "error":
            return [], q, payload
        if payload:
            return payload, q, _broadened_note(q, subject)
    return [], last_q, _broadened_note(last_q, subject)


# --- Dispatch: singolo provider o fan-out multi-provider (B8) ---------------
def _provider_list() -> list[str]:
    names = [p.strip().lower() for p in (settings.search_provider or "").split(",") if p.strip()]
    return names or ["mock"]


async def _run_one(name: str, subject: dict, mode: str, max_results: int,
                   lang: str, timespan: str) -> tuple[list[dict], str, str | None]:
    if name == "gdelt":
        return await _gdelt(subject, mode, max_results, lang, timespan)
    if name == "brave":
        return await _brave(subject, mode, max_results, lang, timespan)
    if name == "searxng":
        return await _searxng(subject, mode, max_results, lang, timespan)
    if name == "mock":
        return _mock(subject, mode, max_results), qb.build_query(subject, mode), None
    return [], "", f"provider sconosciuto: {name}"


async def search(subject: dict, mode: str, max_results: int, lang: str,
                 timespan: str) -> tuple[list[dict], str, str | None]:
    """Ritorna (risultati_grezzi, query_effettiva, note). Con un solo provider si
    comporta come prima; con più provider (lista in SEARCH_PROVIDER) fa il
    **fan-out parallelo** con merge, dedup per URL e boost di corroborazione."""
    names = _provider_list()
    if len(names) == 1:
        return await _run_one(names[0], subject, mode, max_results, lang, timespan)

    async def _guarded(n: str):
        try:
            return await asyncio.wait_for(
                _run_one(n, subject, mode, max_results, lang, timespan),
                timeout=settings.search_fanout_timeout,
            )
        except Exception as exc:  # noqa: BLE001 — un provider lento/rotto non blocca gli altri
            return ([], "", f"{type(exc).__name__}")

    outcomes = await asyncio.gather(*[_guarded(n) for n in names])
    merged: dict[str, dict] = {}
    order: list[str] = []
    queries: list[str] = []
    notes: list[str] = []
    for name, (items, query, note) in zip(names, outcomes):
        if query:
            queries.append(f"{name}:{query}")
        if note:
            notes.append(f"{name}: {note}")
        for it in items:
            u = it.get("url")
            if not u:
                continue
            if u not in merged:
                merged[u] = {**it, "_providers": set()}
                order.append(u)
            merged[u]["_providers"].add(name)

    # Corroborazione: i URL trovati da PIÙ provider vanno in cima (il postprocessing
    # poi ordina per credibilità mantenendo quest'ordine dentro ciascun tier).
    order.sort(key=lambda u: -len(merged[u]["_providers"]))
    results: list[dict] = []
    for u in order:
        d = merged[u]
        provs = sorted(d.pop("_providers"))
        d["provider"] = "+".join(provs)
        d["corroborations"] = len(provs)
        results.append(d)

    note = " · ".join(notes) if notes else None
    return results, " | ".join(queries), note
