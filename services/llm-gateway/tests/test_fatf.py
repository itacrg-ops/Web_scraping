"""Normalizzazione dell'output del modello e combinazione dual-LLM dei campi che
chiudono il caso: soggetto deceduto e anno dell'ultimo fatto avverso.

    python services/llm-gateway/tests/test_fatf.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import fatf  # noqa: E402

YEAR = datetime.now(timezone.utc).year


def test_deceduto_solo_se_affermato() -> None:
    assert fatf.normalize({"soggetto_deceduto": True})["soggetto_deceduto"] is True
    assert fatf.normalize({"soggetto_deceduto": "sì"})["soggetto_deceduto"] is True
    for v in (None, False, "false", "no", "forse", 1, "unknown"):
        assert fatf.normalize({"soggetto_deceduto": v})["soggetto_deceduto"] is False, v
    assert fatf.normalize({})["soggetto_deceduto"] is False


def test_anno_ultimo_fatto_plausibile() -> None:
    assert fatf.normalize({"anno_ultimo_fatto": 2009})["anno_ultimo_fatto"] == 2009
    assert fatf.normalize({"anno_ultimo_fatto": "1992"})["anno_ultimo_fatto"] == 1992
    assert fatf.normalize({"anno_ultimo_fatto": "2016-11-17"})["anno_ultimo_fatto"] == 2016
    for v in (None, "", "n.d.", 1850, YEAR + 1, True, "boh"):
        assert fatf.normalize({"anno_ultimo_fatto": v})["anno_ultimo_fatto"] is None, v


def test_il_prompt_chiede_i_campi() -> None:
    assert '"soggetto_deceduto"' in fatf.SYSTEM_PROMPT and '"anno_ultimo_fatto"' in fatf.SYSTEM_PROMPT


def _classify(primary: dict, secondary: dict | None, person: bool = True) -> dict:
    from app import foundry
    from app.config import settings
    answers = [primary] + ([secondary] if secondary else [])
    saved = (foundry._client, foundry._classify_one, settings.pii_redaction, settings.llm_model_secondary)
    foundry._client = lambda: None
    foundry._classify_one = lambda client, model, text: fatf.normalize(answers.pop(0))
    settings.pii_redaction = False
    settings.llm_model_secondary = "secondario" if secondary else ""
    try:
        return foundry.classify("testo", subject_name="Rossi Mario", subject_person=person, dual=True)
    finally:
        foundry._client, foundry._classify_one, settings.pii_redaction, settings.llm_model_secondary = saved


def test_dual_chiude_solo_se_i_modelli_concordano() -> None:
    try:
        import openai  # noqa: F401
    except ModuleNotFoundError as exc:
        print(f"  (saltato: {exc})")
        return
    dead = {"soggetto_deceduto": True, "anno_ultimo_fatto": 2009}
    alive = {"soggetto_deceduto": False, "anno_ultimo_fatto": 2021}
    out = _classify(dead, alive)
    assert out["soggetto_deceduto"] is False and out["anno_ultimo_fatto"] == 2021, out   # il più recente
    out = _classify(dead, {"soggetto_deceduto": True, "anno_ultimo_fatto": None})
    assert out["soggetto_deceduto"] is True and out["anno_ultimo_fatto"] is None, out     # anno non concorde
    out = _classify(dead, None)                                                             # un solo modello
    assert out["soggetto_deceduto"] is True and out["anno_ultimo_fatto"] == 2009, out
    out = _classify(dead, dead, person=False)                                               # impresa
    assert out["soggetto_deceduto"] is False and out["anno_ultimo_fatto"] == 2009, out


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("TUTTI OK")
