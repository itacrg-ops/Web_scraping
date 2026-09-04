"""Tassonomia FATF, prompt di sistema e normalizzazione dell'output del modello."""
from __future__ import annotations

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
- "fatf_categories": lista (anche vuota) scelta SOLO tra: {FATF_CATEGORIES}
- "ruolo_processuale": uno tra {RUOLI_PROCESSUALI} oppure null
- "role_analysis": uno tra {ROLE_ANALYSIS} (il ruolo del soggetto rispetto ai fatti)
- "severity": uno tra {SEVERITY}
- "confidence": numero tra 0 e 1
- "rationale": breve motivazione in italiano (max 300 caratteri) ancorata al testo
Regole:
- Se non emergono reati o red flag, "fatf_categories" = [] e "severity" = "bassa".
- Rispetta la presunzione di innocenza: distingui indagine da condanna in "ruolo_processuale".
- Non inventare: attieniti a ciò che il testo afferma."""


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
    return {
        "fatf_categories": cats,
        "ruolo_processuale": ruolo,
        "role_analysis": role,
        "severity": sev,
        "confidence": conf,
        "rationale": rationale,
    }
