"""Ruoli del soggetto (persona fisica) citati negli articoli.

- **Cariche pubbliche e politiche.** Quelle dell'elenco del D.Lgs. 231/2007 (art. 1,
  c. 2, lett. dd) rendono la persona una possibile **PEP** (persona politicamente
  esposta): ministri e sottosegretari, parlamentari, presidenti, assessori e consiglieri
  regionali, sindaci di capoluoghi o di comuni con almeno 15.000 abitanti, membri degli
  organi direttivi centrali dei partiti, giudici delle giurisdizioni superiori,
  ambasciatori, vertici delle autorità indipendenti, direttori generali delle ASL…
  Resta un'indicazione da verificare («verifica» quando dipende da ciò che l'articolo
  non dice, come gli abitanti del comune). Le altre cariche politiche (assessore o
  consigliere comunale, vicesindaco…) sono «ruolo politico», senza flag PEP.
- **Ruoli aziendali e professionali**: amministratore delegato (AD, CEO), direttore
  generale (DG), presidente, consigliere di amministrazione, legale rappresentante,
  titolare, socio, dirigente, RUP…

Il ruolo conta solo se è scritto ACCANTO al nome, nella stessa frase: «il sindaco di
Roma Mario Rossi», «Mario Rossi, amministratore delegato di Acme», «Mario Rossi è l'ex
ministro…». Un ruolo altrove nell'articolo può appartenere a un'altra persona.
"""
from __future__ import annotations

import re

# Classificazione (ruolo + ente, in quest'ordine: dal più specifico):
# (espressione, tipo, categoria, pep). pep: "si" (carica dell'elenco), "verifica"
# (dipende da dati che l'articolo non dà), None.
_KINDS: list[tuple[str, str, str, str | None]] = [
    (r"presidente della repubblica", "presidente della Repubblica", "pep", "si"),
    (r"presidente del consiglio dei ministri|premier", "presidente del Consiglio", "pep", "si"),
    (r"vice\s?-?ministr[oa]", "viceministro", "pep", "si"),
    (r"ministr[oa]", "ministro", "pep", "si"),
    (r"sottosegretari[oa]", "sottosegretario", "pep", "si"),
    (r"president[ea] della (?:regione|giunta regionale)|governat(?:ore|rice) della regione",
     "presidente della Regione", "pep", "si"),
    (r"president[ea] del consiglio regionale", "presidente del consiglio regionale", "pep", "si"),
    (r"assessor[ea] regionale", "assessore regionale", "pep", "si"),
    (r"consiglier[ea] regionale", "consigliere regionale", "pep", "si"),
    (r"europarlamentare|eurodeputat[oa]|parlamentare europe[oa]", "parlamentare europeo", "pep", "si"),
    (r"deputat[oa]|onorevole", "deputato", "pep", "si"),
    (r"senat(?:ore|rice)", "senatore", "pep", "si"),
    (r"parlamentare", "parlamentare", "pep", "si"),
    (r"(?:segretari[oa]|tesorier[ea]|president[ea]) (?:nazionale|federale)", "vertice nazionale di partito", "pep", "si"),
    (r"giudice (?:della )?corte costituzionale", "giudice costituzionale", "pep", "si"),
    (r"consiglier[ea] di stato", "consigliere di Stato", "pep", "si"),
    (r"(?:magistrat[oa]|consiglier[ea]) (?:della )?(?:corte di )?cassazione", "magistrato di Cassazione", "pep", "si"),
    (r"(?:president[ea]|consiglier[ea]|procurat(?:ore|rice)(?: generale)?) della corte dei conti",
     "magistrato della Corte dei conti", "pep", "si"),
    (r"magistrat[oa]", "magistrato", "pubblico", None),
    (r"ambasciat(?:ore|rice)", "ambasciatore", "pep", "si"),
    (r"governat(?:ore|rice) della banca d['’]italia", "governatore della Banca d'Italia", "pep", "si"),
    (r"(?:president[ea]|componente|commissari[oa]) (?:dell['’]|della |del )?"
     r"(?:anac|consob|agcom|agcm|antitrust|ivass|arera|garante)", "vertice di autorità indipendente", "pep", "si"),
    (r"(?:direttore|direttrice) generale (?:dell['’]|della |del )?(?:asl|asp|ausl|ats|azienda (?:sanitaria|ospedaliera))",
     "direttore generale di azienda sanitaria", "pep", "si"),
    (r"sindac[oa] (?:effettiv[oa]|supplente)|president[ea] del collegio sindacale", "sindaco (collegio sindacale)",
     "aziendale", None),
    (r"vice\s?-?sindac[oa]", "vicesindaco", "politico", None),
    (r"sindac[oa]", "sindaco", "pep", "verifica"),                 # PEP se capoluogo o ≥ 15.000 abitanti
    (r"generale|ammiraglio", "generale", "pep", "verifica"),       # PEP se di grado apicale
    (r"governat(?:ore|rice)", "presidente della Regione", "pep", "si"),
    (r"president[ea] del consiglio (?:comunale|municipale|provinciale)", "presidente del consiglio comunale",
     "politico", None),
    (r"assessor[ea](?: comunale| municipale)?", "assessore", "politico", None),
    (r"consiglier[ea] (?:comunale|municipale|provinciale|metropolitan[oa])", "consigliere comunale", "politico", None),
    (r"president[ea] (?:della provincia|del municipio)", "presidente di provincia o municipio", "politico", None),
    (r"componente|commissari[oa]", "componente o commissario", "pubblico", None),
    (r"responsabile unico del procedimento|rup", "RUP", "pubblico", None),
    (r"funzionari[oa]", "funzionario", "pubblico", None),
    (r"amministrat(?:ore|rice) delegat[oa]|ad|a\.d\.|ceo", "amministratore delegato", "aziendale", None),
    (r"amministrat(?:ore|rice) unic[oa]", "amministratore unico", "aziendale", None),
    (r"(?:direttore|direttrice) generale|dg|d\.g\.", "direttore generale", "aziendale", None),
    (r"consiglier[ea] delegat[oa]", "consigliere delegato", "aziendale", None),
    (r"consiglier[ea] (?:di amministrazione|del cda)", "consigliere di amministrazione", "aziendale", None),
    (r"legale rappresentante|rappresentante legale", "legale rappresentante", "aziendale", None),
    (r"direttore finanziario|cfo", "direttore finanziario", "aziendale", None),
    (r"direttore operativo|coo", "direttore operativo", "aziendale", None),
    (r"vice\s?-?president(?:e|essa)", "vicepresidente", "aziendale", None),
    (r"president(?:e|essa)", "presidente", "aziendale", None),
    (r"procurat(?:ore|rice) speciale", "procuratore speciale", "aziendale", None),
    (r"titolare", "titolare", "aziendale", None),
    (r"soci[oa](?: unic[oa]| di maggioranza| fondat(?:ore|rice))?", "socio", "aziendale", None),
    (r"fondat(?:ore|rice)", "fondatore", "aziendale", None),
    (r"dirigente", "dirigente", "aziendale", None),
    (r"manager", "manager", "aziendale", None),
    (r"imprenditr?(?:ore|ice)", "imprenditore", "aziendale", None),
]
_KIND_RX = [(re.compile(rx, re.IGNORECASE), kind, cat, pep) for rx, kind, cat, pep in _KINDS]

# Parole di ruolo da cercare accanto al nome (l'ente che segue — "di Roma", "dell'Asl
# Roma 1" — è catturato a parte). Dalle più lunghe; sigle solo in maiuscolo ("ad
# esempio" non è un amministratore delegato); il grado militare solo dopo un articolo.
_ROLE_WORDS = "|".join([
    r"presidente del consiglio dei ministri", r"premier", r"vice\s?-?ministr[oa]", r"ministr[oa]",
    r"sottosegretari[oa]", r"president[ea] (?:della giunta regionale|del consiglio (?:regionale|comunale|municipale"
    r"|provinciale)|del collegio sindacale|nazionale|federale)", r"assessor[ea] (?:regionale|comunale|municipale)",
    r"assessor[ea]", r"consiglier[ea] (?:regionale|comunale|municipale|provinciale|metropolitan[oa]|delegat[oa]"
    r"|di amministrazione|del cda|di stato)", r"europarlamentare", r"eurodeputat[oa]", r"parlamentare europe[oa]",
    r"deputat[oa]", r"onorevole", r"senat(?:ore|rice)", r"parlamentare", r"(?:segretari[oa]|tesorier[ea]) (?:nazionale|federale)",
    r"giudice (?:della )?corte costituzionale", r"magistrat[oa]", r"ambasciat(?:ore|rice)", r"governat(?:ore|rice)",
    r"componente", r"commissari[oa]", r"sindac[oa] (?:effettiv[oa]|supplente)", r"vice\s?-?sindac[oa]", r"sindac[oa]",
    r"(?:(?<=il )|(?<=al )|(?<=del )|(?<=dal )|(?<=col ))(?:generale|ammiraglio)",
    r"responsabile unico del procedimento", r"(?-i:RUP)", r"funzionari[oa]",
    r"amministrat(?:ore|rice) (?:delegat[oa]|unic[oa])", r"(?-i:AD)", r"a\.d\.", r"(?-i:CEO)",
    r"(?:direttore|direttrice) (?:generale|finanziario|operativo)", r"(?-i:DG)", r"d\.g\.", r"(?-i:CFO)", r"(?-i:COO)",
    r"legale rappresentante", r"rappresentante legale", r"vice\s?-?president(?:e|essa)", r"president(?:e|essa)",
    r"procurat(?:ore|rice) speciale", r"titolare", r"soci[oa](?: unic[oa]| di maggioranza| fondat(?:ore|rice))?",
    r"fondat(?:ore|rice)", r"dirigente", r"manager", r"imprenditr?(?:ore|ice)",
])


def _org(lazy: bool) -> str:
    """Ente dopo il ruolo: "di Roma", "della Regione Lazio", "dell'Asl Roma 1" (parole con
    iniziale maiuscola: case-sensitive anche in un'espressione IGNORECASE). Pigro quando
    dopo viene il nome (le parole maiuscole del nome non sono dell'ente)."""
    more = "*?" if lazy else "{0,4}"
    return (r"(?P<org>\s+(?:di|del|della|dello|dei|degli|delle|dell['’]|d['’])\s*"
            rf"(?-i:[A-ZÀ-Ý][\w'’.&-]*(?:\s+(?:[A-ZÀ-Ý][\w'’.&-]*|\d+)){more}))?")


_EX = r"(?P<ex>\b(?:ex|già)\s+|\bex-)?"
_GAP = r"[^.;!?\n]{0,40}?"   # inciso breve nella stessa frase ("58 anni,")


def _name_rx(subject: dict) -> str | None:
    nome = (subject.get("nome") or "").split()
    cognome = (subject.get("cognome") or "").split()
    if not (nome and cognome):
        toks = (subject.get("denominazione") or "").split()
        cognome, nome = toks[:1], toks[1:]
    if not (nome and cognome):
        return None
    a = r"\s+".join(map(re.escape, nome + cognome))
    b = r"\s+".join(map(re.escape, cognome + nome))
    return rf"(?:{a}|{b})\b"


def classify(role: str, org: str = "") -> tuple[str, str, str | None]:
    """(tipo, categoria, pep) del ruolo, considerando anche l'ente: "direttore generale"
    + "dell'Asl Roma 1" è una carica PEP, "presidente" + "della Regione Lazio" anche."""
    full = f"{role} {org}".strip()
    for rx, kind, cat, pep in _KIND_RX:
        m = rx.match(full)
        if m and m.end() >= len(role):
            return kind, cat, pep
    return role.lower(), "aziendale", None


def _display(role: str, org: str) -> str:
    """Ruolo come scritto nell'articolo; minuscola iniziale se era solo inizio frase."""
    if role[:1].isupper() and role[1:2].islower():
        role = role[0].lower() + role[1:]
    return f"{role} {org}".strip()


def extract(subject: dict, text: str) -> list[dict]:
    """Ruoli scritti accanto al nome della persona nel testo, senza duplicati:
    [{"ruolo": "sindaco di Roma", "tipo": "sindaco", "categoria": "pep",
      "pep": "verifica", "ex": False}]."""
    if (subject.get("tipo_soggetto") or "") != "persona_fisica" or not text:
        return []
    name = _name_rx(subject)
    if not name:
        return []
    role = rf"(?P<role>\b(?:{_ROLE_WORDS})\b)"
    art = r"(?:(?:l['’]|il|la|lo|attuale|nuovo|nuova)\s*)*"
    patterns = [
        # «il sindaco di Roma Mario Rossi», «l'ex ministro Mario Rossi»
        rf"{_EX}{role}{_org(lazy=True)}\s*,?\s+{name}",
        # «Mario Rossi, amministratore delegato di Acme», «Mario Rossi (AD di Acme)»
        rf"{name}\s*[,(–—-]\s*(?:{_GAP},\s*)?{art}{_EX}{role}{_org(lazy=False)}",
        # «Mario Rossi è l'amministratore delegato di Acme», «… era il sindaco di X»
        rf"{name}\s+(?:è|era|è stato|è stata|fu|resta|diventa)\s+{art}{_EX}{role}{_org(lazy=False)}",
    ]
    found: dict[str, dict] = {}
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            role_text = " ".join(m.group("role").split())
            org = " ".join((m.group("org") or "").split())
            kind, cat, pep = classify(role_text, org)
            ex = bool(m.group("ex"))
            shown = ("ex " if ex else "") + _display(role_text, org)
            found.setdefault(shown.lower(), {"ruolo": shown, "tipo": kind, "categoria": cat, "pep": pep, "ex": ex})
    return list(found.values())


def summarize(per_article: list[list[dict]]) -> list[dict]:
    """Ruoli di più articoli: uno per ruolo, con in quanti articoli compare; prima le
    cariche PEP, poi le più citate."""
    out: dict[str, dict] = {}
    for roles in per_article:
        for key, r in {x["ruolo"].lower(): x for x in roles}.items():
            if key in out:
                out[key]["articoli"] += 1
            else:
                out[key] = {**r, "articoli": 1}
    return sorted(out.values(), key=lambda r: (r["categoria"] != "pep", -r["articoli"], r["ruolo"]))


def is_pep(roles: list[dict]) -> bool:
    """Possibile PEP: almeno una carica dell'elenco (anche da verificare)."""
    return any(r.get("pep") for r in roles)
