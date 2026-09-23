"""Esito dello screening quando la pipeline è DEGRADATA (logica pura e deterministica,
usata dal workflow Temporal).

Un guasto non deve mai produrre un esito che sembri valido:
- ricerca fallita / nessun contenuto recuperato → NON "nessun segnale" (AUTO_CHIUSO:
  falsa rassicurazione);
- LLM non disponibile → le categorie a keyword NON bastano per un'escalation
  automatica né per una chiusura.
In questi casi la disposition diventa **ESITO_INCOMPLETO** (da ripetere o completare
a mano), il livello di rischio "N/D" e i motivi vanno in testa alla motivazione.
"""
from __future__ import annotations

INCOMPLETE = "ESITO_INCOMPLETO"


def incomplete_reasons(*, search_error: str | None, urls: list[str], docs_with_text: int,
                       classification: dict, risk_feed: dict | None) -> list[str]:
    """Motivi per cui l'esito non è affidabile (lista vuota = esito valido).

    `search_error`: errore della ricerca automatica (None se riuscita o non eseguita).
    `urls`: fonti da analizzare; `docs_with_text`: quante hanno dato testo utile."""
    reasons: list[str] = []
    if search_error:
        reasons.append(f"ricerca articoli non riuscita ({search_error})")
    if urls and docs_with_text == 0:
        reasons.append(f"nessun contenuto recuperato dalle {len(urls)} fonti "
                       "(robots.txt, paywall o errori di rete)")
    elif docs_with_text and classification.get("method") == "euristica_keyword":
        why = classification.get("fallback_reason") or "LLM non disponibile"
        reasons.append(f"classificazione a parole chiave ({why}): categorie non affidabili")
    if risk_feed and risk_feed.get("error"):
        reasons.append(f"feed di rischio {risk_feed.get('provider')} non raggiungibile "
                       f"({risk_feed.get('reason')})")
    return reasons


def apply_incomplete(outcome: dict, reasons: list[str]) -> dict:
    """Applica i motivi all'esito {ami_score, risk_level, disposition, drivers}.
    Senza motivi lo restituisce invariato."""
    if not reasons:
        return outcome
    return {
        **outcome,
        "risk_level": "N/D",
        "disposition": INCOMPLETE,
        "drivers": [
            "⚠ ESITO INCOMPLETO — screening da ripetere o completare a mano: " + "; ".join(reasons),
            f"AMI {outcome.get('ami_score')} solo indicativo: calcolato su dati incompleti",
            *outcome.get("drivers", []),
        ],
    }
