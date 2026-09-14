"""svi_core — libreria generica per pubblicare alert in SAS Visual Investigator.

Uso tipico (nell'adapter dell'app):

    from svi_core import SviAlert, publish, settings

    async def publish_my_alert(my_obj):
        alert = SviAlert(
            business_key=my_obj.case_id,
            entity_id=my_obj.tax_id or my_obj.case_id,
            entity_label=my_obj.name,
            score=my_obj.risk_score,
            trigger_text=my_obj.explanation,
            enrichment={"risk_level": my_obj.level, "category": my_obj.category},
        )
        return await publish(alert)          # usa `settings` (da .env) se cfg non passato

Config da ambiente/.env (prefissi SVI_/SAS_/VIYA_). Vedi templates/.env.svi.example.
"""
from .auth import bearer, build_oauth_request, reset_cache
from .client import publish, reset_idempotency
from .config import SviConfig, settings
from .envelope import build_alerting_payload
from .models import SviAlert

__all__ = [
    "SviAlert",
    "SviConfig",
    "settings",
    "publish",
    "reset_idempotency",
    "build_alerting_payload",
    "bearer",
    "build_oauth_request",
    "reset_cache",
]
