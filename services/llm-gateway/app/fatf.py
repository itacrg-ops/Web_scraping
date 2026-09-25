"""Tassonomia FATF, prompt di sistema e normalizzazione dell'output del modello."""
from __future__ import annotations

from datetime import datetime, timezone

# Categorie FATF per l'adverse media (etichette canoniche: il modello deve
# scegliere ESCLUSIVAMENTE tra queste).
FATF_CATEGORIES = [
    "Fraud & Financial Crime",
    "Corruption & Bribery",
    "Money Laundering",
    "Organized Crime",
    "Terrorist Financing",
    "Tax Crimes",
    "Sanctions & Embargoes",
    "Trafficking (Human/Drugs/Arms)",
    "Environmental Crime",
    "Cybercrime",
    "Market Manipulation & Securities",
    "Regulatory & Compliance",
]

RUOLI_PROCESSUALI = [
    "notizia_di_reato", "indagine_preliminare", "rinvio_a_giudizio",
    "condanna_non_definitiva", "condanna_definitiva", "archiviazione",
]
ROLE_ANALYSIS = ["perpetratore", "vittima", "menzionato"]
SEVERITY = ["bassa", "media", "alta"]

SYSTEM_PROMPT = f"""Sei un classificatore di adverse media per la pubblica amministrazione italiana, secondo la tassonomia FATF.
Analizza il TESTO fornito e restituisci ESCLUSIVAMENTE un oggetto JSON valido con i campi:
- "fatf_categories": lista (anche vuota) scelta SOLO tra: {FATF_CATEGORIES} — i reati o
  red flag attribuiti al soggetto in esame (indicato nel testo come [SOGGETTO], se c'è),
  non quelli di altre persone o società citate
- "ruolo_processuale": uno tra {RUOLI_PROCESSUALI} oppure null
- "role_analysis": uno tra {ROLE_ANALYSIS}: il ruolo del soggetto in esame rispetto ai
  fatti — "perpetratore" se gli sono attribuiti (anche solo come indagato), "vittima" se
  li subisce, "menzionato" se è solo citato (cliente, fornitore, controparte, luogo…)
- "severity": uno tra {SEVERITY}
- "confidence": numero tra 0 e 1
- "rationale": breve motivazione in italiano (max 300 caratteri) ancorata al testo
- "soggetto_deceduto": true SOLO se il soggetto in esame è una persona e il testo afferma
  che è morto (deceduto, ucciso, «il defunto», «la morte di», «scomparso» solo se vuol dire
  morto: non se è irreperibile o latitante); altrimenti false
- "anno_ultimo_fatto": anno (4 cifre) del fatto avverso PIÙ RECENTE attribuito al soggetto
  (reato, indagine, arresto, rinvio a giudizio, condanna, sequestro, sanzione): l'anno del
  fatto, non quello in cui l'articolo lo ricorda. Se il fatto è datato solo in modo relativo
  («ieri», «il mese scorso») o il procedimento è ancora in corso, usa l'anno di
  pubblicazione dell'articolo (indicato prima di ogni articolo). null se non ci sono fatti
  avversi o se l'anno del più recente non si ricava dal testo
Regole:
- Se non emergono reati o red flag, "fatf_categories" = [] e "severity" = "bassa".
- Rispetta la presunzione di innocenza: distingui indagine da condanna in "ruolo_processuale".
- Non inventare: attieniti a ciò che il testo afferma."""


def _year(value) -> int | None:
    """Anno plausibile (1900..anno corrente) o None."""
    try:
        year = int(str(value).strip()[:4]) if value not in (None, "", False) else None
    except (TypeError, ValueError):
        return None
    return year if year is not None and 1900 <= year <= datetime.now(timezone.utc).year else None


def normalize(data: dict) -> dict:
    """Valida/normalizza l'output del modello contro la tassonomia."""
    cats = [c for c in (data.get("fatf_categories") or []) if c in FATF_CATEGORIES]
    ruolo = data.get("ruolo_processuale")
    ruolo = ruolo if ruolo in RUOLI_PROCESSUALI else None
    role = data.get("role_analysis")
    role = role if role in ROLE_ANALYSIS else None
    sev = data.get("severity")
    sev = sev if sev in SEVERITY else ("bassa" if not cats else "media")
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        conf = 0.0
    rationale = (data.get("rationale") or None)
    if isinstance(rationale, str):
        rationale = rationale[:300]
    dead = data.get("soggetto_deceduto")
    dead = dead is True or (isinstance(dead, str) and dead.strip().lower() in ("true", "si", "sì"))
    return {
        "fatf_categories": cats,
        "ruolo_processuale": ruolo,
        "role_analysis": role,
        "severity": sev,
        "confidence": conf,
        "rationale": rationale,
        # chiusura del caso (worker, compute_ami): persona morta o fatti non recenti
        "soggetto_deceduto": dead,
        "anno_ultimo_fatto": _year(data.get("anno_ultimo_fatto")),
    }
