# Adverse Media Screening — FSC / Pilota MASE

Applicazione di **web scraping e analisi multi-agente per l'adverse media screening** dei beneficiari, soggetti attuatori e imprese esecutrici degli interventi finanziati dal **Fondo per lo Sviluppo e la Coesione (FSC)** di competenza del **MASE**, a supporto dei controlli desk di I livello (Si.Ge.Co. / SIM).

Lo strumento è un **ausilio istruttorio** (decision-support) *explainable* e auditabile: individua e ordina per priorità le verifiche, ma **non decide** — la determinazione resta all'istruttore, senza scoring automatico (conforme a GDPR e AI Act).

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| [`docs/WebScraping_AdverseMedia_FSC_MASE.md`](docs/WebScraping_AdverseMedia_FSC_MASE.md) | Documento tecnico-funzionale **(v1.1)**: architettura, modulo di scraping, fonti, modello dati, governance e piano di sviluppo |
| [`docs/NOTE_DI_REVISIONE.md`](docs/NOTE_DI_REVISIONE.md) | Memo di revisione esperta: rilievi ordinati per criticità, razionale e punti aperti |

## Pilastri di progetto

- **Compliant by design** — base giuridica art. 10 GDPR per i dati giudiziari, DPIA + FRIA (art. 27 AI Act), HITL, audit trail immutabile.
- **Anti-omonimia** — Entity Resolution obbligatoria (matching deterministico su CF/P.IVA/CUP) prima di qualsiasi giudizio.
- **Materialità** — ogni alert è ancorato allo specifico intervento (**CUP/CIG**) e al ruolo del soggetto.
- **Fonti sostenibili** — feed licenziati come spina dorsale, scraping conforme (robots.txt / ToS / opt-out TDM) sulle fonti pubbliche istituzionali.
- **Sinergia, non duplicazione** — complementare ad ARACHNE/PIAF; aggiunge il segnale "notizie negative".

## Stato

Repository in fase di **avvio**: al momento contiene la documentazione tecnico-funzionale. Le fasi implementative (Entity Resolution, scraper MVP, classificazione FATF, AMI scoring) sono descritte nel piano di sviluppo del documento tecnico.
