"""Mappatura del feed di rischio → dominio adverse-media (FATF / AMI / evidenza).

Traduce la risposta **normalizzata** di un provider di rischio (indicatori per
tipo di reato + rete di connessioni) nel vocabolario già usato dalla pipeline:

- gli **indicatori di rischio** → categorie **FATF** (stesse etichette del
  classificatore media, così si fondono senza duplicati) + una **severità**
  aggregata che alimenta l'AMI;
- le **connessioni** (rete dell'entità) → **driver** esplicabili e **evidenza
  strutturata** (non un URL/articolo: un legame verso un'altra entità a rischio).

Funzioni **pure e deterministiche** (nessun I/O): facili da testare e da
spiegare in audit. I nomi dei campi del provider sono normalizzati a monte
(nel client), così qui non dipendiamo dallo schema esterno.
"""
from __future__ import annotations

from typing import Any

# tipo di reato (Crime&tech) → categoria FATF (stesse etichette del media
# classifier: services/worker-scraping/classifier.py). Le chiavi sono confrontate
# per sotto-stringa, minuscole, così tolleriamo varianti/lingue del provider.
_CRIME_TO_FATF: list[tuple[str, str]] = [
    ("corrupt", "Corruption & Bribery"),
    ("bribe", "Corruption & Bribery"),
    ("corruz", "Corruption & Bribery"),
    ("concuss", "Corruption & Bribery"),
    ("bid rig", "Corruption & Bribery"),
    ("turbativ", "Corruption & Bribery"),
    ("fraud", "Fraud & Financial Crime"),
    ("frode", "Fraud & Financial Crime"),
    ("embezzl", "Fraud & Financial Crime"),
    ("tax", "Fraud & Financial Crime"),
    ("fiscal", "Fraud & Financial Crime"),
    ("evasion", "Fraud & Financial Crime"),
    ("launder", "Money Laundering"),
    ("ricicl", "Money Laundering"),
    ("organized", "Organized Crime"),
    ("organised", "Organized Crime"),
    ("mafia", "Organized Crime"),
    ("traffick", "Organized Crime"),
    ("terror", "Terrorist Financing"),
    ("sanction", "Sanctions & Embargoes"),
    ("embargo", "Sanctions & Embargoes"),
    ("environment", "Environmental Crime"),
    ("ambient", "Environmental Crime"),
]

# rating testuale del provider → severità del nostro dominio (alta|media|bassa).
_RATING_TO_SEVERITY: dict[str, str] = {
    "high": "alta", "alto": "alta", "severe": "alta", "critical": "alta", "red": "alta",
    "medium": "media", "medio": "media", "moderate": "media", "amber": "media", "orange": "media",
    "low": "bassa", "basso": "bassa", "minor": "bassa", "green": "bassa", "yellow": "bassa",
}

_SEVERITY_ORDER = {"bassa": 1, "media": 2, "alta": 3}


def crime_to_fatf(crime_type: str | None) -> str | None:
    """Mappa un tipo di reato del provider su una categoria FATF (o None)."""
    t = (crime_type or "").strip().lower()
    if not t:
        return None
    for needle, cat in _CRIME_TO_FATF:
        if needle in t:
            return cat
    return None


def rating_to_severity(rating: str | None) -> str | None:
    """Normalizza il rating del provider su alta|media|bassa (o None se ignoto)."""
    return _RATING_TO_SEVERITY.get((rating or "").strip().lower())


def _max_severity(values: list[str | None]) -> str | None:
    known = [v for v in values if v in _SEVERITY_ORDER]
    return max(known, key=lambda v: _SEVERITY_ORDER[v]) if known else None


def build_assessment(provider: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Da risposta **normalizzata** del provider all'assessment di dominio.

    `raw` atteso (prodotto dal client del provider):
        {
          "entity_id": str|None,
          "risk_indicators": [
             {"indicator": str, "crime_type": str, "rating": str,
              "score": float|None, "explanation": str}
          ],
          "connections": [
             {"entity": str, "entity_id": str|None, "relationship": str,
              "risk_flag": bool, "crime_type": str|None, "rating": str|None}
          ],
        }
    """
    indicators = raw.get("risk_indicators") or []
    connections = raw.get("connections") or []

    fatf: list[str] = []
    severities: list[str | None] = []
    drivers: list[str] = []
    evidence: list[dict[str, Any]] = []

    for ind in indicators:
        cat = crime_to_fatf(ind.get("crime_type"))
        if cat and cat not in fatf:
            fatf.append(cat)
        sev = rating_to_severity(ind.get("rating"))
        severities.append(sev)
        label = ind.get("indicator") or ind.get("crime_type") or "indicatore"
        rating = ind.get("rating")
        expl = ind.get("explanation")
        driver = f"Indicatore di rischio ({provider}): {label}"
        if rating:
            driver += f" — livello {rating}"
        if cat:
            driver += f" [{cat}]"
        if expl:
            driver += f". {expl}"
        drivers.append(driver)

    risky_conns = [c for c in connections if c.get("risk_flag")]
    for c in risky_conns:
        who = c.get("entity") or c.get("entity_id") or "entità collegata"
        rel = c.get("relationship") or "collegamento"
        ccat = crime_to_fatf(c.get("crime_type"))
        if ccat and ccat not in fatf:
            fatf.append(ccat)
        severities.append(rating_to_severity(c.get("rating")))
        drv = f"Connessione a rischio ({provider}): {rel} → {who}"
        if ccat:
            drv += f" [{ccat}]"
        drivers.append(drv)
        evidence.append({
            "tipo": "connessione",
            "provider": provider,
            "entity": who,
            "entity_id": c.get("entity_id"),
            "relationship": rel,
            "crime_type": c.get("crime_type"),
            "fatf_category": ccat,
        })

    severity = _max_severity(severities)
    n_ind = len(indicators)
    n_conn = len(risky_conns)
    summary = (f"Feed di rischio {provider}: {n_ind} indicatori"
               + (f", {n_conn} connessioni a rischio" if n_conn else "")
               + (f"; severità aggregata {severity}" if severity else ""))
    drivers.insert(0, summary)

    return {
        "provider": provider,
        "available": True,
        "entity_id": raw.get("entity_id"),
        "fatf_categories": fatf,
        "severity": severity,
        "risk_indicators": indicators,
        "connections": connections,
        "drivers": drivers,
        "evidence": evidence,
    }


def unavailable(provider: str, reason: str) -> dict[str, Any]:
    """Assessment 'non disponibile' (feed OFF, entità non riconciliata, errore):
    contratto stabile per il worker, che semplicemente non arricchisce l'alert."""
    return {
        "provider": provider,
        "available": False,
        "reason": reason,
        "entity_id": None,
        "fatf_categories": [],
        "severity": None,
        "risk_indicators": [],
        "connections": [],
        "drivers": [],
        "evidence": [],
    }
