# Note di revisione esperta — Adverse Media Screening FSC/MASE
### Memo tecnico a supporto della v1.1 del capitolato

> Scopo: motivare i rilievi e le modifiche apportate al documento tecnico-funzionale, con priorità, razionale e raccomandazioni operative. Il documento di partenza (v1.0) è **solido e ben strutturato**; i rilievi che seguono riguardano i punti a maggior rischio giuridico/operativo, quelli che un DPO, l'Autorità di Audit o la Corte dei conti verificherebbero per primi.

Legenda criticità: 🔴 bloccante · 🟠 alta · 🟡 media · 🟢 miglioria.

---

## Sintesi esecutiva

Il progetto è ben impostato sul piano dell'architettura (multi-agente, HITL, explainability) e della strategia (consumo di ARACHNE/PIAF, no duplicazione). I tre rischi che possono farlo deragliare **non sono tecnici**:

1. 🔴 **La base giuridica per i dati giudiziari (art. 10 GDPR)**. È il rilievo n.1. Senza norma abilitante, il trattamento del cuore stesso dell'adverse media (indagini, condanne) è illegittimo, a prescindere dalla qualità del codice.
2. 🟠 **La sostenibilità delle fonti**. Lo scraping "puro" delle testate è fragile e a basso rendimento; la spina dorsale realistica sono i feed licenziati + fonti pubbliche istituzionali.
3. 🟠 **La difendibilità dell'alert**. Un alert è utile al I livello solo se è *materiale* rispetto allo specifico intervento (CUP) e rispetta la presunzione d'innocenza (ruolo processuale).

Questi tre punti sono stati portati in primo piano nella v1.1.

---

## Rilievi

### R1 🔴 Base giuridica per i dati relativi a reati (art. 10 GDPR)
**Osservazione.** La v1.0 (§8) fonda il trattamento su art. 6(1)(e) GDPR + art. 2-*ter* Codice Privacy. Questi coprono i **dati comuni**, ma l'adverse media screening tratta, per definizione, **dati relativi a condanne penali e reati** (art. 10 GDPR). Per tali dati l'art. 10 GDPR e l'**art. 2-*octies*** del Codice Privacy richiedono un'autorizzazione da **legge o regolamento** che individui finalità e garanzie.
**Perché conta.** È la contestazione più immediata e più difficile da sanare a valle. Senza base normativa specifica, gli alert basati su notizie giudiziarie non sono trattabili in produzione.
**Raccomandazione.** Attività del **giorno 1**: con il legale, mappare la norma abilitante nel perimetro dei controlli FSC (o promuovere l'atto regolamentare). Fino ad allora, la pipeline può girare su dati **non** giudiziari (registri, doppio finanziamento) ma non produrre alert fondati su reati.
**Stato v1.1.** Recepito in §8.1, §9 (Avvio), §10, §11 e come dipendenza nel Gantt.

### R2 🟠 Strategia sulle fonti: *build-vs-buy*
**Osservazione.** La v1.0 tratta lo scraping come canale principale e i feed licenziati come opzione "dove disponibili". Nella pratica AML/KYC è l'inverso: lo scraping generalista è il canale **più fragile** (paywall, ToS anti-TDM, robots, layout drift) e a **minor resa strutturata**.
**Perché conta.** Incide su costi, rischio legale e qualità/recall. Un pilota che punta sullo scraping delle testate rischia bassa copertura e alto attrito legale.
**Raccomandazione.** Gerarchia esplicita: (1) feed licenziati come spina dorsale; (2) API/open data istituzionali; (3) scraping mirato di fonti pubbliche ad alto valore/basso rischio (albo pretorio, BUR, comunicati Procure/GdF, ANAC); (4) testate solo su licenza e nel rispetto dell'**opt-out TDM** (art. 4 Dir. UE 2019/790; artt. 70-*ter*/70-*quater* L. 633/1941).
**Stato v1.1.** Recepito in §4.3 e §5 (registro fonti).

### R3 🟠 Materialità dell'alert rispetto al CUP
**Osservazione.** L'AMI v1.0 misura il rischio del *soggetto*. Manca il nesso con lo *specifico intervento*.
**Perché conta.** Il I livello agisce su "questa bad news incide su *questo* CUP", non su "il soggetto ha precedenti". La materialità è ciò che rende l'alert azionabile **e** difendibile (proporzionalità, pertinenza).
**Raccomandazione.** Introdurre un fattore di **materialità** (nesso CUP/CIG × ruolo del soggetto × importo/fase) nell'AMI e nell'output.
**Stato v1.1.** Recepito in §7.3, §7.4 (JSON), §5.

### R4 🟠 Presunzione d'innocenza e ruolo processuale
**Osservazione.** La v1.0 distingue autore/vittima/menzionato ma non la **fase** (indagato ≠ imputato ≠ condannato ≠ archiviato).
**Perché conta.** Trattare un indagato come colpevole viola l'art. 27 Cost. e genera rischio legale/reputazionale. Un'archiviazione nota deve azzerare il peso dell'evidenza.
**Raccomandazione.** Campo obbligatorio `ruolo_processuale` con decadenza dell'AMI su archiviazioni/proscioglimenti; retention e "oblio" conseguenti.
**Stato v1.1.** Recepito in §7.2, §7.4, §8.4, §11.

### R5 🟠 AI Act: FRIA e sorveglianza umana
**Osservazione.** La v1.0 cita "DPIA + AIA". L'acronimo corretto per l'obbligo dei deployer pubblici è **FRIA — Fundamental Rights Impact Assessment (art. 27 AI Act)**, distinto dalla DPIA (art. 35 GDPR). Va inoltre esplicitata la **sorveglianza umana effettiva** (art. 14).
**Raccomandazione.** DPIA + FRIA come gate di go-live; HITL con potere di override reale, non formale.
**Stato v1.1.** Recepito in §8.2, §9, §11.

### R6 🟡 Algoritmo amministrativo (giurisprudenza italiana)
**Osservazione.** Manca il riferimento ai principi consolidati del Consiglio di Stato (conoscibilità, non esclusività, non discriminazione).
**Perché conta.** È il quadro con cui un giudice amministrativo valuterebbe un provvedimento supportato da algoritmo; rafforza e "italianizza" il design HITL.
**Stato v1.1.** Recepito in §8.3.

### R7 🟡 Ciclo di vita del dato, retention e diritto alla cancellazione
**Osservazione.** La v1.0 cita minimizzazione e audit immutabile ma non concilia i due (un audit immutabile che trattiene dati personali confligge con gli artt. 16-17 GDPR).
**Raccomandazione.** Tabella di retention per categoria; audit su identificatori pseudonimizzati/hash; cancellazione del contenuto via **crypto-shredding**/tombstoning.
**Stato v1.1.** Recepito in §8.4 e §8.5.

### R8 🟡 Monitoraggio del bias
**Osservazione.** L'adverse media sovra-segnala nomi esteri, alias e translitterazioni; senza misura, il bias resta invisibile.
**Raccomandazione.** Metriche di falsi positivi per categoria a rischio, riportate nel set di validazione.
**Stato v1.1.** Recepito in §8.6, §10, §11.

### R9 🟡 Valore probatorio dell'evidenza
**Osservazione.** Hash e snapshot WARC assicurano integrità, ma non la **data certa**.
**Raccomandazione.** Marca temporale **qualificata (eIDAS)** su ogni evidenza; conservazione dello snapshot collegato.
**Stato v1.1.** Recepito in §4.1, §4.3, §7.4, §10.

### R10 🟢 Registro fonti e credibilità
**Osservazione.** Il campo `fonte_credibilita` era una stima ad-hoc.
**Raccomandazione.** Alimentarlo da un **registro fonti** con criteri documentati (credibilità + rischio legale + politeness).
**Stato v1.1.** Recepito in §5.1.

### R11 🟢 Sicurezza e residenza dati (PA)
**Osservazione.** Utile esplicitare misure minime AgID, cloud qualificato ACN e residenza dati UE.
**Stato v1.1.** Recepito in §6 e §8.7.

---

## Punti aperti / da decidere con il committente

Non sono difetti del documento, ma decisioni che incidono su costi e tempi e vanno prese presto:

- **Budget feed licenziati.** C'è copertura per Dow Jones/LexisNexis/Moody's Grid, o il pilota parte "open-only"? La scelta cambia radicalmente la resa e il rischio dello scraping.
- **Perimetro persone fisiche vs giuridiche.** Quanto si spinge lo screening sugli **UBO** (persone fisiche)? È il punto di massimo rischio GDPR/AI Act e va perimetrato nella DPIA.
- **Soglie e disposizioni.** Chi definisce le soglie AMI e la mappatura soglia→disposizione (auto-chiusura vs escalation)? Va concordato con il I livello e versionato.
- **Multilinguismo.** Copertura di fonti estere per UBO non italiani: quali lingue e con quali risorse NER/traduzione.
- **SLA e ampiezza del pilota.** Numero di CUP/soggetti del pilota MASE, per dimensionare code, storage snapshot e costi LLM.

---

## Cosa NON è stato cambiato (e perché)

- **Architettura multi-agente e stack**: appropriati; mantenuti.
- **Tassonomia FATF**: scelta corretta e standard per l'adverse media in ambito AML/KYC; mantenuta.
- **Approccio "consumo, non duplico" verso ARACHNE/PIAF**: giusto; mantenuto.
- **Early-termination / abstain-by-default**: buona pratica; mantenuta.

---

*Memo interno a corredo della v1.1. I riferimenti normativi sono di indirizzo progettuale e vanno validati con legale/DPO in sede di DPIA e FRIA.*
