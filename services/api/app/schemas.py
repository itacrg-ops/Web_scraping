"""Schemi Pydantic esposti dall'API (contratto per console e worker)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(BaseModel):
    """Voce del registro fonti (§5.1)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    nome: str
    tipo: str = Field(description="feed | api | scraping")
    credibilita: str
    rischio_legale: str
    crawl_delay_s: float = 2.0
    respect_robots: bool = True
    attiva: bool = True


class ScreeningRequest(BaseModel):
    """Richiesta di avvio screening (dalla console).

    Supporta due tipi di soggetto:
      - `persona_giuridica` (default): si indica la `denominazione`;
      - `persona_fisica`: si indicano `nome` e `cognome` (e, per disambiguare
        l'omonimia, il Codice Fiscale a 16 caratteri o la `data_nascita`).
    Per la persona fisica la `denominazione` viene composta come "Cognome Nome".
    """

    tipo_soggetto: str = Field(default="persona_giuridica",
                               description="persona_giuridica | persona_fisica")
    denominazione: str | None = None
    nome: str | None = None            # solo persona fisica
    cognome: str | None = None         # solo persona fisica
    data_nascita: str | None = None    # ISO YYYY-MM-DD, disambiguante (persona fisica)
    luogo_nascita: str | None = None   # comune/stato di nascita, disambiguante (persona fisica)
    cf_piva: str | None = None
    # Qualificatori di ricerca (persona fisica): azienda/località entrano nella
    # query in AND forte; ruolo è soft (corroborazione a valle, non nella query).
    azienda: str | None = None
    localita: str | None = None
    ruolo: str | None = None
    cup: list[str] = []
    # Sorgenti da screenare (precedenza: seed_url → seed_urls → ricerca automatica):
    seed_url: str | None = None         # URL singolo (override manuale)
    seed_urls: list[str] = []           # articoli scelti in console (web search)
    max_articles: int | None = None     # max articoli in modalità ricerca automatica

    @model_validator(mode="after")
    def _compose_denominazione(self) -> "ScreeningRequest":
        if self.tipo_soggetto == "persona_fisica" and not self.denominazione:
            self.denominazione = " ".join(p for p in (self.cognome, self.nome) if p).strip()
        if not (self.denominazione and self.denominazione.strip()):
            raise ValueError(
                "indicare la denominazione (persona giuridica) oppure nome e cognome (persona fisica)"
            )
        return self


class SubjectCreate(BaseModel):
    """Nuovo soggetto del registro (dalla console). Per la persona fisica
    compone `denominazione` = "Cognome Nome"."""

    tipo_soggetto: str = Field(default="persona_giuridica",
                               description="persona_giuridica | persona_fisica")
    denominazione: str | None = None
    nome: str | None = None
    cognome: str | None = None
    data_nascita: str | None = None
    luogo_nascita: str | None = None
    cf_piva: str | None = None
    cup: list[str] = []
    ruolo: str | None = None
    attivo: bool = True

    @model_validator(mode="after")
    def _compose_denominazione(self) -> "SubjectCreate":
        if self.tipo_soggetto == "persona_fisica" and not self.denominazione:
            self.denominazione = " ".join(p for p in (self.cognome, self.nome) if p).strip()
        if not (self.denominazione and self.denominazione.strip()):
            raise ValueError(
                "indicare la denominazione (persona giuridica) oppure nome e cognome (persona fisica)"
            )
        return self


class SubjectUpdate(BaseModel):
    """Modifica (parziale) di un soggetto — solo i campi inviati vengono applicati."""

    tipo_soggetto: str | None = None
    denominazione: str | None = None
    cf_piva: str | None = None
    data_nascita: str | None = None
    luogo_nascita: str | None = None
    cup: list[str] | None = None
    ruolo: str | None = None
    attivo: bool | None = None


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tipo_soggetto: str
    denominazione: str
    cf_piva: str | None = None
    data_nascita: str | None = None
    luogo_nascita: str | None = None
    cup: list[str] = []
    ruolo: str | None = None
    attivo: bool = True
    created_at: datetime


class SubjectImportRequest(BaseModel):
    """Import massivo del registro da CSV (testo). Colonne attese (header):
    tipo_soggetto, denominazione, nome, cognome, cf_piva, data_nascita, cup, ruolo.
    `cup` separati da `;`. Upsert per CF/P.IVA quando presente."""

    csv: str


class SubjectImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    errors: list[str] = []


class ScreeningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    denominazione: str
    tipo_soggetto: str = "persona_giuridica"
    status: str
    error: str | None = None
    alert_id: str | None = None
    created_at: datetime


class ScreeningFailure(BaseModel):
    """Esito di fallimento della pipeline (dal worker)."""

    error: str


class EvidenceItem(BaseModel):
    """Evidenza esposta (risposta)."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    url: str | None = None
    testata: str | None = None
    title: str | None = None
    data: str | None = None
    snippet: str | None = None
    content_hash: str | None = None
    fetch_ts: str | None = None
    warc_key: str | None = None
    fonte_credibilita: str | None = None
    mentioned: bool | None = None           # predizione: soggetto citato nell'articolo
    mention_match: list[str] | None = None  # come (cf_piva / nome_cognome / denominazione…)


class EvidenceCreate(BaseModel):
    """Evidenza in ingresso (dal worker), con riferimenti allo snapshot."""

    url: str | None = None
    testata: str | None = None
    title: str | None = None
    data: str | None = None
    snippet: str | None = None
    content_hash: str | None = None
    fetch_ts: str | None = None
    bucket: str | None = None
    raw_key: str | None = None
    warc_key: str | None = None
    fonte_credibilita: str | None = None
    mentioned: bool | None = None
    mention_match: list[str] | None = None


SviStatus = Literal["pending", "published", "failed", "skipped"]


class AlertCreate(BaseModel):
    """Payload di persistenza alert (dal worker, PRIMA della pubblicazione in SVI)."""

    screening_id: str | None = None
    subject: str
    tipo_soggetto: str = "persona_giuridica"
    cf_piva: str | None = None
    cup: list[str] = []
    ami_score: int
    risk_level: str
    fatf_categories: list[str] = []
    drivers: list[str] = []
    disposition: str = "ESCALATION_I_LIVELLO"
    svi_alert_id: str | None = None
    svi_status: SviStatus = "pending"
    entity_resolution: dict | None = None
    classification: dict | None = None   # metodo llm/keyword, severità, ruolo… (valutazione)
    evidence: list[EvidenceCreate] = []


class AlertSviUpdate(BaseModel):
    """Esito della pubblicazione in SVI (dal worker, dopo il tentativo)."""

    svi_status: SviStatus
    svi_alert_id: str | None = None
    svi_error: str | None = None


class Alert(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    screening_id: str | None = None
    subject: str
    tipo_soggetto: str = "persona_giuridica"
    cf_piva: str | None = None
    cup: list[str] = []
    ami_score: int
    risk_level: str
    fatf_categories: list[str] = []
    drivers: list[str] = []
    disposition: str
    svi_alert_id: str | None = None
    svi_status: str = "pending"
    svi_error: str | None = None
    entity_resolution: dict | None = None
    classification: dict | None = None
    evidence: list[EvidenceItem] = []
    created_at: datetime


# --- Etichette dei casi (dataset di valutazione) ---------------------------------
# Stessa lista del llm-gateway (app/fatf.py): le etichette devono essere confrontabili
# con le predizioni, quindi niente categorie libere.
FATF_CATEGORIES = [
    "Fraud & Financial Crime", "Corruption & Bribery", "Money Laundering", "Organized Crime",
    "Terrorist Financing", "Tax Crimes", "Sanctions & Embargoes", "Trafficking (Human/Drugs/Arms)",
    "Environmental Crime", "Cybercrime", "Market Manipulation & Securities", "Regulatory & Compliance",
]
Pertinenza = Literal["si", "omonimo", "non_citato", "incerto"]   # l'articolo riguarda il soggetto?
Avversa = Literal["si", "no", "incerto"]                        # la notizia è avversa per lui?
Ruolo = Literal["autore_indagato", "vittima", "menzionato", "non_determinabile"]
DispositionAttesa = Literal["ESCALATION_I_LIVELLO", "AUTO_CHIUSO"]


class EvidenceLabel(BaseModel):
    pertinenza: Pertinenza | None = None
    avversa: Avversa | None = None


class CaseLabelIn(BaseModel):
    """Giudizio del revisore. `affidabile` = caso da includere nel dataset: richiede un
    giudizio completo e senza "incerto" (vedi `missing_for_reliable`)."""

    evidence_labels: dict[str, EvidenceLabel] = {}
    categorie_corrette: list[str] = []
    ruolo: Ruolo | None = None
    disposition_attesa: DispositionAttesa | None = None
    affidabile: bool = False
    note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _known_categories(self) -> "CaseLabelIn":
        unknown = [c for c in self.categorie_corrette if c not in FATF_CATEGORIES]
        if unknown:
            raise ValueError(f"categorie FATF sconosciute: {unknown}")
        self.categorie_corrette = list(dict.fromkeys(self.categorie_corrette))
        return self

    def missing_for_reliable(self, evidence_ids: list[str]) -> list[str]:
        """Cosa manca perché il caso sia un esempio affidabile per il dataset."""
        missing = []
        if self.disposition_attesa is None:
            missing.append("disposition attesa")
        if self.ruolo is None:
            missing.append("ruolo del soggetto")
        for eid in evidence_ids:
            lab = self.evidence_labels.get(eid)
            if lab is None or lab.pertinenza in (None, "incerto") or lab.avversa in (None, "incerto"):
                missing.append(f"giudizio certo su pertinenza e avversità dell'articolo {eid}")
        return missing


class CaseLabelOut(CaseLabelIn):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_id: str
    reviewer: str
    reviewer_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseLabelSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    alert_id: str
    affidabile: bool
    updated_at: datetime | None = None


class LabelStats(BaseModel):
    etichettati: int                 # casi con almeno un'etichetta
    affidabili: int                  # casi con almeno un'etichetta "affidabile"
    revisori: int
    # Distribuzione per disposition PREDETTA dal sistema: rivela il bias di selezione
    # (se si etichettano solo le escalation si misura la precisione ma non i falsi negativi).
    per_disposition: dict[str, int] = {}
    affidabili_per_disposition: dict[str, int] = {}
