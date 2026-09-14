"""Template di ADAPTER: dominio dell'applicazione → SVI (via svi_core).

Copia questo file nel tuo servizio e adattalo. L'adapter è l'UNICA parte
app-specific: traduce il tuo oggetto di dominio in un `SviAlert` canonico e chiama
`svi_core.publish`. Tutto il resto (auth, envelope, retry, idempotenza) è in svi_core.

Passi:
  1. definisci come ricavare i campi canonici dal tuo oggetto (vedi build_svi_alert);
  2. scegli una `business_key` STABILE per l'idempotenza (id caso/screening): stessa
     chiave → nessun alert duplicato, anche su ripubblicazione/retry;
  3. popola `enrichment` con i campi che vuoi memorizzare sull'alert (enrichmentJson);
  4. configura il `.env` (SVI_ENTITY_TYPE, SVI_QUEUE, SVI_ALERT_TYPE_CODE, auth…);
  5. testa con scripts/svi_smoketest.py, poi metti SVI_MODE=live.
"""
from __future__ import annotations

from typing import Any

from svi_core import SviAlert, publish


def build_svi_alert(obj: dict[str, Any]) -> SviAlert:
    """Mappa il tuo oggetto di dominio (qui un dict d'esempio) su SviAlert.

    Adatta i nomi dei campi. `entity_id` è l'id dell'entità azionabile (es. CF/P.IVA,
    id cliente…); se manca, usa la business key come fallback. `trigger_text` è la
    motivazione leggibile mostrata di default sull'alert. `enrichment` sono i campi
    strutturati (poi visibili configurando la pagina alert in SVI — vedi onboarding)."""
    business_key = str(obj["case_id"])                       # ← id stabile del tuo caso
    entity_id = obj.get("tax_id") or business_key            # ← actionableEntityId
    # Fonti/evidenze come testo ("titolo: url" per riga) → campo enrichment mostrabile.
    fonti = "\n".join(f"{e.get('source','fonte')}: {e['url']}"
                      for e in (obj.get("evidence") or []) if e.get("url"))
    enrichment = {
        "risk_level": obj.get("risk_level", ""),
        "category": obj.get("category", ""),
        # sintesi breve (per la griglia) + link fonti (per il dettaglio):
        "rationale_sintesi": (obj.get("explanation", "") or "")[:300],
        "fonti": fonti,
        # aggiungi qui altri campi custom (valori stringa) da mostrare sull'alert.
        # NB: il Name del campo nella griglia SVI deve combaciare byte-per-byte (case!).
        # Per evidenze STRUTTURATE (oggetti con url) usa invece SviAlert.contributing_objects.
    }
    return SviAlert(
        business_key=business_key,
        entity_id=entity_id,
        entity_label=obj.get("name") or entity_id,           # nome leggibile in coda
        score=int(obj.get("score") or 0),                    # score core dell'alert
        trigger_text=obj.get("explanation", ""),             # motivazione (alertTriggerText)
        enrichment={k: v for k, v in enrichment.items() if v},
    )


async def publish_alert(obj: dict[str, Any]) -> dict[str, Any]:
    """Entry-point dell'adapter: costruisce l'SviAlert e pubblica (idempotente)."""
    alert = build_svi_alert(obj)
    return await publish(alert)                              # usa `settings` da .env


if __name__ == "__main__":
    import asyncio
    demo = {"case_id": "CASE-1", "tax_id": "00743110157", "name": "ACME S.r.l.",
            "score": 82, "risk_level": "ALTO", "category": "AML",
            "explanation": "Motivazione leggibile dell'alert…"}
    print(asyncio.run(publish_alert(demo)))                  # SVI_MODE=mock → id fittizio
