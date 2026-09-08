"""NER (Named Entity Recognition) italiano via spaCy — B7 parte 2.

Estrae persone (PER), organizzazioni (ORG) e luoghi (LOC) dagli articoli. Serve:
  - alla corroborazione anti-omonimia nel worker (il soggetto è riconosciuto come
    PERSONA? l'azienda come ORGANIZZAZIONE?);
  - in prospettiva a B1.1 (redazione dei nomi propri di terzi prima dell'LLM).

Caricamento **lazy** del modello (`it_core_news_sm`) e **degradazione graziosa**:
se spaCy/il modello non sono disponibili, ritorna `available: False` senza
sollevare, così i chiamanti restano sulla logica a stringhe.
"""
from __future__ import annotations

import functools
import logging

logger = logging.getLogger("llm-gateway.ner")

# Componenti non necessari alla NER: disattivarli velocizza l'inferenza.
_DISABLE = ["parser", "lemmatizer", "attribute_ruler", "tagger", "morphologizer"]
_MAX_CHARS = 20000


@functools.lru_cache(maxsize=1)
def _nlp():
    import spacy  # import lazy: dipendenza pesante

    return spacy.load("it_core_news_sm", disable=_DISABLE)


def available() -> bool:
    try:
        _nlp()
        return True
    except Exception as exc:  # noqa: BLE001 — modello assente/incompatibile
        logger.warning("NER non disponibile: %s", exc)
        return False


def extract(text: str) -> dict:
    """Ritorna {available, persons, orgs, locations, entities}. Non solleva."""
    try:
        nlp = _nlp()
    except Exception as exc:  # noqa: BLE001
        logger.warning("NER non disponibile: %s", exc)
        return {"available": False, "persons": [], "orgs": [], "locations": [], "entities": []}

    doc = nlp((text or "")[:_MAX_CHARS])
    entities = [{"text": e.text, "label": e.label_} for e in doc.ents]

    def _by(label: str) -> list[str]:
        # dedup preservando un ordine stabile (alfabetico)
        return sorted({e["text"].strip() for e in entities if e["label"] == label and e["text"].strip()})

    return {
        "available": True,
        "persons": _by("PER"),
        "orgs": _by("ORG"),
        "locations": _by("LOC"),
        "entities": entities,
    }
