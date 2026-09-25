"""Parti PURE dell'analisi di uno screening, condivise dal workflow Temporal e dalla
rivalutazione del dataset (`replay.py`): quale testo va alla classificazione, quali
segnali pesano l'AMI, come si fonde il feed di rischio, cosa si salva della
classificazione. Stanno in un solo posto perché la rivalutazione misuri esattamente
la logica in produzione. Funzioni deterministiche: sicure nel contesto workflow.
"""
from __future__ import annotations

MAX_CLASSIFY_CHARS = 12000    # cap del testo aggregato inviato alla classificazione
_SEV_ORDER = {"bassa": 1, "media": 2, "alta": 3}
# Predizione del classificatore salvata sull'alert (valutazione vs etichette dei revisori).
CLASSIFICATION_KEYS = ("method", "severity", "ruolo_processuale", "role_analysis",
                       "secondary_agreement", "confidence", "fallback_reason",
                       "soggetto_deceduto", "anno_ultimo_fatto")


def classification_text(docs: list[dict]) -> str:
    """Testo per la classificazione: gli articoli che citano il soggetto; se nessuno
    lo cita, tutti quelli con contenuto (il workflow lo segnala nei driver). Ogni
    articolo porta la sua data di pubblicazione: serve a datare i fatti («ieri», «il
    processo è in corso») per l'anno dell'ultimo fatto avverso."""
    with_text = [d for d in docs if d.get("text")]
    chosen = [d for d in with_text if d.get("_mentioned")] or with_text
    parts = [f"[Articolo {i}, " + (f"pubblicato il {d['date']}]" if d.get("date")
                                   else "data di pubblicazione non nota]") + "\n" + d["text"]
             for i, d in enumerate(chosen, 1)]
    return "\n\n".join(parts)[:MAX_CLASSIFY_CHARS]


def ami_signals(docs: list[dict]) -> list[dict]:
    """Segnali per la pesatura AMI: per ogni articolo fonte, credibilità e se cita il
    soggetto (corroborazione da fonti indipendenti)."""
    return [{"url": d.get("source"), "domain": d.get("_domain"),
             "testata_credibilita": d.get("_credibilita"), "mentioned": d.get("_mentioned")}
            for d in docs]


def merge_risk_feed(classification: dict, risk_feed: dict) -> dict:
    """Fonde il feed di rischio strutturato nella classificazione media: unione
    delle categorie FATF (senza duplicati) e severità = massimo tra media e feed.
    Così un riscontro dal feed alza l'AMI anche quando gli articoli tacciono."""
    merged = dict(classification)
    cats = list(merged.get("fatf_categories") or [])
    for c in risk_feed.get("fatf_categories") or []:
        if c not in cats:
            cats.append(c)
    merged["fatf_categories"] = cats
    sev_feed = risk_feed.get("severity")
    if _SEV_ORDER.get(sev_feed, 0) > _SEV_ORDER.get(merged.get("severity"), 0):
        merged["severity"] = sev_feed
    return merged


def saved_classification(classification: dict) -> dict:
    """La parte della classificazione salvata sull'alert (confronto con le etichette)."""
    return {k: classification.get(k) for k in CLASSIFICATION_KEYS}
