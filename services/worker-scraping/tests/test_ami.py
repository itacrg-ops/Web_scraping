"""AMI ed esito: chiusura del caso quando il soggetto non ha un rischio attuale —
persona deceduta secondo gli articoli, o ultimo fatto avverso più vecchio di
AMI_FATTI_VECCHI_ANNI (regola dei revisori). Logica pura, nessuna rete.

    python services/worker-scraping/tests/test_ami.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import activities  # noqa: E402
from analysis import classification_text, saved_classification  # noqa: E402

YEAR = datetime.now(timezone.utc).year
PF = {"tipo_soggetto": "persona_fisica", "denominazione": "Provenzano Bernardo"}
PG = {"tipo_soggetto": "persona_giuridica", "denominazione": "Fami Srl"}
SIGNALS = [{"url": "https://www.ansa.it/a", "testata_credibilita": "alta", "mentioned": True}]


def _ami(subject: dict, **classification) -> dict:
    cls = {"fatf_categories": ["Organized Crime"], "severity": "media", "role_analysis": "perpetratore",
           **classification}
    return asyncio.run(activities.compute_ami(subject, cls, SIGNALS))


def test_fatti_recenti_escalation() -> None:
    # 68 × 1.05 (alta) × 0.95 (fonte unica) = 68
    r = _ami(PF, anno_ultimo_fatto=YEAR - 2)
    assert r["ami_score"] == 68 and r["disposition"] == "ESCALATION_I_LIVELLO", r
    assert not r["drivers"][0].startswith("Chiuso")


def test_persona_deceduta_chiusa() -> None:
    r = _ami(PF, soggetto_deceduto=True, anno_ultimo_fatto=YEAR - 2)
    assert r["ami_score"] == 25 and r["risk_level"] == "BASSO" and r["disposition"] == "AUTO_CHIUSO", r
    assert r["drivers"][0].startswith("Chiuso: secondo gli articoli il soggetto è deceduto"), r["drivers"]
    formula = next(d for d in r["drivers"] if d.startswith("AMI = base"))
    assert formula.endswith("= 68 → 25 (tetto: nessun rischio attuale)"), formula


def test_impresa_non_muore() -> None:
    assert _ami(PG, soggetto_deceduto=True)["disposition"] == "ESCALATION_I_LIVELLO"


def test_fatti_vecchi_chiusi() -> None:
    r = _ami(PG, anno_ultimo_fatto=YEAR - 11)
    assert r["disposition"] == "AUTO_CHIUSO" and r["ami_score"] == 25, r
    assert r["drivers"][0] == (f"Chiuso: fatti non recenti — l'ultimo fatto avverso attribuito al soggetto è "
                               f"del {YEAR - 11}, oltre 10 anni fa"), r["drivers"][0]
    assert _ami(PG, anno_ultimo_fatto=YEAR - 10)["disposition"] == "ESCALATION_I_LIVELLO"   # non oltre
    assert _ami(PG, anno_ultimo_fatto=None)["disposition"] == "ESCALATION_I_LIVELLO"        # anno ignoto


def test_regole_disattivabili() -> None:
    saved = (activities.AMI_CHIUDI_DECEDUTI, activities.AMI_FATTI_VECCHI_ANNI)
    activities.AMI_CHIUDI_DECEDUTI, activities.AMI_FATTI_VECCHI_ANNI = False, 0
    try:
        r = _ami(PF, soggetto_deceduto=True, anno_ultimo_fatto=1992)
    finally:
        activities.AMI_CHIUDI_DECEDUTI, activities.AMI_FATTI_VECCHI_ANNI = saved
    assert r["disposition"] == "ESCALATION_I_LIVELLO", r


def test_vittima_resta_col_suo_tetto() -> None:
    r = _ami(PF, role_analysis="vittima")
    assert r["ami_score"] == 25 and r["disposition"] == "AUTO_CHIUSO"
    assert any(d.endswith("→ 25 (tetto: soggetto vittima)") for d in r["drivers"]), r["drivers"]
    assert not r["drivers"][0].startswith("Chiuso")


def test_nessuna_categoria_invariato() -> None:
    r = asyncio.run(activities.compute_ami(PF, {"fatf_categories": [], "soggetto_deceduto": True}, SIGNALS))
    assert r["ami_score"] == 8 and r["disposition"] == "AUTO_CHIUSO"


def test_testo_con_date_e_campi_salvati() -> None:
    docs = [{"text": "Arrestato ieri.", "date": "2024-05-02", "_mentioned": True},
            {"text": "Condannato nel 2003.", "_mentioned": True},
            {"text": "Altro soggetto.", "date": "2025-01-01", "_mentioned": False}]
    assert classification_text(docs) == ("[Articolo 1, pubblicato il 2024-05-02]\nArrestato ieri.\n\n"
                                         "[Articolo 2, data di pubblicazione non nota]\nCondannato nel 2003.")
    saved = saved_classification({"method": "llm_dual", "soggetto_deceduto": True, "anno_ultimo_fatto": 2003})
    assert saved["soggetto_deceduto"] is True and saved["anno_ultimo_fatto"] == 2003


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("TUTTI OK")
