"""Registro di credibilità delle testate + normalizzazione dominio.

Alla ricerca si applicano due passaggi di qualità (§5.1 del capitolato —
governo delle fonti):
  - **deduplica per dominio**: un solo articolo (o pochi) per testata, per
    favorire la corroborazione da fonti indipendenti;
  - **credibilità della testata**: ogni risultato è annotato con un livello
    (alta | media | bassa | sconosciuta) e si può filtrare sotto una soglia.

Il registro qui è un **seed curato e governabile** (in produzione è gestito
centralmente, come il registro fonti/feed). Non è esaustivo né un giudizio
editoriale: è una base per pesare/filtrare l'affidabilità in fase di triage.
"""
from __future__ import annotations

from urllib.parse import urlparse

# Ordinamento dei livelli (per sort e soglia di filtro). "sconosciuta" (testata
# non ancora a registro) è sopra "bassa" (nota come poco affidabile): un dominio
# non catalogato non va trattato peggio di uno noto-scadente. Coerente con l'AMI.
CRED_RANK: dict[str, int] = {"alta": 3, "media": 2, "sconosciuta": 1, "bassa": 0}

# Suffissi pubblici composti più comuni (per estrarre il dominio registrabile).
_COMPOUND_SUFFIXES = {
    "co.uk", "gov.uk", "org.uk", "ac.uk", "com.au", "co.jp",
    "gov.it", "edu.it",
}

# Registro seed testata→credibilità (chiave = dominio registrabile, minuscolo).
# NB: valori illustrativi e governabili; i domini *.example sono per il mock.
_TESTATE: dict[str, str] = {
    # --- Agenzie e testate nazionali (alta) ---
    "ansa.it": "alta", "agi.it": "alta", "ilsole24ore.com": "alta",
    "corriere.it": "alta", "repubblica.it": "alta", "lastampa.it": "alta",
    "ilfattoquotidiano.it": "alta", "rainews.it": "alta", "adnkronos.com": "alta",
    "ilmessaggero.it": "alta", "ilpost.it": "alta", "open.online": "alta",
    # --- Testate locali/regionali e online generaliste (media) ---
    "lanuovasardegna.it": "media", "unionesarda.it": "media", "ilmattino.it": "media",
    "iltirreno.it": "media", "ilgazzettino.it": "media", "gazzettadelsud.it": "media",
    "quotidiano.net": "media", "fanpage.it": "media", "today.it": "media",
    "leggo.it": "media", "mediaset.it": "media",
    # --- Piattaforme UGC / blog (bassa) ---
    "blogspot.com": "bassa", "wordpress.com": "bassa", "medium.com": "bassa",
    # --- Domini del provider mock (per la demo locale) ---
    "ilmessaggero.example": "alta", "larepubblica.example": "alta",
    "ansa.example": "alta", "cronacalocale.example": "media",
    "blognotizie.example": "bassa",
}


def domain_of(url: str) -> str:
    """Dominio registrabile (minuscolo), senza `www.` e senza sottodomini.
    Es. https://roma.repubblica.it/... → repubblica.it."""
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last2 = ".".join(labels[-2:])
    if last2 in _COMPOUND_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last2


def credibility_of(domain: str) -> str:
    return _TESTATE.get(domain, "sconosciuta")


def postprocess(results: list[dict], *, dedup_by_domain: bool, max_per_domain: int,
                min_credibility: str, max_results: int) -> tuple[list[dict], int]:
    """Annota (dominio + credibilità), filtra sotto soglia, ordina per
    credibilità (poi per ordine originale), deduplica per dominio e tronca.
    Ritorna (risultati, quanti rimossi tra filtro e dedup)."""
    for i, r in enumerate(results):
        d = domain_of(r.get("url", ""))
        r["domain"] = d or None
        r["testata_credibilita"] = credibility_of(d) if d else "sconosciuta"
        r["_idx"] = i

    kept = results
    if min_credibility and min_credibility != "none":
        floor = CRED_RANK.get(min_credibility, 0)
        kept = [r for r in kept if CRED_RANK.get(r["testata_credibilita"], 0) >= floor]

    # Credibilità decrescente, poi ordine originale (stabile: recenza nel tier).
    kept = sorted(kept, key=lambda r: (-CRED_RANK.get(r["testata_credibilita"], 0), r["_idx"]))

    if dedup_by_domain:
        seen: dict[str, int] = {}
        deduped: list[dict] = []
        for r in kept:
            key = r.get("domain") or r.get("url") or ""
            if seen.get(key, 0) < max_per_domain:
                deduped.append(r)
                seen[key] = seen.get(key, 0) + 1
        kept = deduped

    removed = len(results) - len(kept)
    kept = kept[:max_results]
    for r in kept:
        r.pop("_idx", None)
    return kept, removed
