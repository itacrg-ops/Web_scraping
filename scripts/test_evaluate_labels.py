"""Test dello script di valutazione su un dataset sintetico con risultati noti.

    python scripts/test_evaluate_labels.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

import evaluate_labels as ev  # noqa: E402


def _rec(aid, disp, cats, label, evidence, method="llm_dual", affidabile=True):
    return {"schema": "ams-case-label/1",
            "alert": {"id": aid, "subject": f"Soggetto {aid}", "disposition": disp,
                      "fatf_categories": cats, "classification": {"method": method}},
            "label": {"affidabile": affidabile, **label}, "evidence": evidence}


def _ev(mentioned, pertinenza, match=("denominazione",)):
    return {"url": f"https://x/{pertinenza}", "mentioned": mentioned, "mention_match": list(match),
            "label": {"pertinenza": pertinenza, "avversa": "no"}}


RECORDS = [
    # sistema escala, revisore chiude (falso positivo); menzione: 1 corretta + 1 omonimo
    _rec("A", "ESCALATION_I_LIVELLO", ["Money Laundering"],
         {"categorie_corrette": [], "disposition_attesa": "AUTO_CHIUSO"},
         [_ev(True, "si"), _ev(True, "omonimo", ("denominazione_breve",))], method="euristica_keyword"),
    # sistema chiude, revisore escala (falso negativo); menzione mancata + negativo vero
    _rec("B", "AUTO_CHIUSO", ["Corruption & Bribery"],
         {"categorie_corrette": ["Corruption & Bribery", "Fraud & Financial Crime"],
          "disposition_attesa": "ESCALATION_I_LIVELLO"},
         [_ev(False, "si", ()), _ev(False, "non_citato", ()), _ev(True, "incerto")]),
    # esito incompleto: non deciso dal sistema
    _rec("C", "ESITO_INCOMPLETO", [], {"categorie_corrette": [], "disposition_attesa": "ESCALATION_I_LIVELLO"}, []),
    # bozza (non affidabile): esclusa per default
    _rec("D", "AUTO_CHIUSO", [], {"categorie_corrette": [], "disposition_attesa": "AUTO_CHIUSO"},
         [_ev(True, "si")], affidabile=False),
]


def _load(records, **kw):
    with tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False, encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in records))
    try:
        return ev.load(fh.name, **kw)
    finally:
        os.unlink(fh.name)


def test_only_reliable_by_default() -> None:
    assert [r["alert"]["id"] for r in _load(RECORDS)] == ["A", "B", "C"]
    assert len(_load(RECORDS, tutti=True)) == 4


def test_mention_metrics() -> None:
    m = ev.mention_metrics(_load(RECORDS))
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)       # "incerto" escluso
    assert m["precisione"]["rate"] == 0.5 and m["richiamo"]["rate"] == 0.5
    assert m["per_tipo_di_match"]["denominazione_breve"]["rate"] == 0.0
    assert m["per_tipo_di_match"]["denominazione"]["rate"] == 1.0
    assert len(m["errori"]) == 2


def test_category_metrics() -> None:
    c = ev.category_metrics(_load(RECORDS))
    assert (c["micro"]["tp"], c["micro"]["fp"], c["micro"]["fn"]) == (1, 1, 1)
    assert c["per_categoria"]["Money Laundering"]["fp"] == 1
    assert c["per_categoria"]["Fraud & Financial Crime"]["fn"] == 1


def test_disposition_metrics() -> None:
    d = ev.disposition_metrics(_load(RECORDS))
    assert d["falsi_positivi"]["k"] == 1 and d["falsi_negativi"]["k"] == 1
    assert d["accordo"]["rate"] == 0.0 and d["non_decisi_dal_sistema"] == 1


def test_per_method_and_agreement() -> None:
    rep = ev.evaluate(_load(RECORDS))
    assert set(rep["per_metodo"]) == {"euristica_keyword", "llm_dual"}
    assert rep["per_metodo"]["euristica_keyword"]["casi"] == 1
    twice = [_rec("A", "AUTO_CHIUSO", [], {"disposition_attesa": d}, []) for d in ("AUTO_CHIUSO", "ESCALATION_I_LIVELLO")]
    assert ev.reviewer_agreement(twice)["rate"] == 0.0


def test_wilson_interval() -> None:
    assert ev.wilson(0, 0)["rate"] is None
    w = ev.wilson(5, 10)
    assert w["rate"] == 0.5 and w["ci95"] == [0.237, 0.763]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
