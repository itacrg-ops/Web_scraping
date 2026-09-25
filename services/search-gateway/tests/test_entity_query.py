"""Ricerca per imprese con nome di una parola ("Vita S.r.l."): la parola da sola è
spesso una parola comune, quindi si cerca la ragione sociale completa e si mettono
prima gli articoli che la citano.

    python services/search-gateway/tests/test_entity_query.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import query as qb  # noqa: E402
from app import testate  # noqa: E402

VITA = {"tipo_soggetto": "persona_giuridica", "denominazione": "Vita S.r.l."}


def test_single_word_company_is_searched_with_legal_form() -> None:
    q = qb.build_query_variants(VITA)
    assert q[0].startswith('("Vita Srl" OR "Vita S.r.l.") (indagato')
    assert all('"Vita"' not in v for v in q)                      # mai la parola comune da sola
    plain = qb.build_query_variants(VITA, syntax="plain")
    assert plain[:2] == ['"Vita Srl" ' + " ".join(qb.ADVERSE_TERMS), '"Vita S.r.l." ' + " ".join(qb.ADVERSE_TERMS)]


def test_legal_form_detected_or_defaulted() -> None:
    spa = {"tipo_soggetto": "persona_giuridica", "denominazione": "Luce SpA"}
    assert qb.name_variants(spa) == ["Luce SpA", "Luce S.p.A."]
    bare = {"tipo_soggetto": "persona_giuridica", "denominazione": "Vita"}
    assert qb.name_variants(bare) == ["Vita Srl", "Vita SpA"]


def test_distinctive_single_word_can_also_go_alone() -> None:
    it = {"tipo_soggetto": "persona_giuridica", "denominazione": "Italware S.r.l."}
    assert qb.name_variants(it) == ["Italware Srl", "Italware S.r.l.", "Italware"]
    assert qb.build_query_variants(it)[-1] == '"Italware"'


def test_multi_word_names_unchanged() -> None:
    acme = {"tipo_soggetto": "persona_giuridica", "denominazione": "ACME Costruzioni S.r.l."}
    assert qb.single_word_entity(acme) is None
    assert qb.build_query_variants(acme)[-1] == '"ACME Costruzioni"'


def test_results_citing_the_company_come_first() -> None:
    raw = [
        {"url": "https://a.it/1", "title": "La vita in città dopo la pandemia"},
        {"url": "https://b.it/2", "title": "Truffa sugli appalti: indagata la Vita S.r.l. di Bologna"},
        {"url": "https://c.it/3", "title": "Sequestro", "snippet": "perquisizioni nella sede di Vita srl"},
    ]
    out, _ = testate.postprocess(raw, dedup_by_domain=False, max_per_domain=9, min_credibility="none",
                                 max_results=9, first=lambda r: qb.cites_full_name(r, VITA))
    assert [r["url"] for r in out] == ["https://b.it/2", "https://c.it/3", "https://a.it/1"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print("TUTTI OK")
