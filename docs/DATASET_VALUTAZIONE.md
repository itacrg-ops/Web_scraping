# Dataset di valutazione — etichettatura dei casi e misura degli errori

Per sapere **quanti errori fa il sistema** (e tarare soglie e regole) servono casi reali
giudicati da chi li conosce. La console permette di etichettare i casi direttamente
nella pagina **Alert**; l'export alimenta lo script di valutazione.

## Come si etichetta un caso

Pagina **Alert** → clicca il caso: si apre la **scheda laterale** (larga quanto lo schermo,
senza scroll orizzontale). Gli articoli sono numerati (**Articolo 1 · testata**) con titolo,
estratto e link, e le due domande subito sotto; poi il giudizio sul caso. Il piè di pagina
resta sempre visibile, con il contatore **Articoli completi: N di M**: **Salva**, oppure
**Salva e successivo** per passare al caso seguente (pulsanti ‹ › in alto per spostarsi, Esc
per chiudere; se ci sono modifiche non salvate viene chiesta conferma).
L'**esito del sistema** (AMI, categorie, motivazione) è in una sezione chiusa: aprila dopo
aver giudicato, per non farti influenzare.

In cima alla scheda, quando serve:
- **possibile refuso nel nome**: gli articoli citano un nome molto simile (es. «Andrea
  Stroppa» per «Stropp Andrea») → «Ripeti lo screening» con il nome corretto;
- **stesso soggetto in altri casi**, con quali sono già nel dataset (vedi *Duplicati*);
- sotto un articolo già giudicato **da te** in un altro caso dello stesso soggetto: «Già
  giudicato da te il …» e **«Usa lo stesso giudizio»** (i giudizi degli altri revisori non
  vengono mostrati: l'etichettatura resta indipendente).

Dopo il salvataggio, **«Conferma nel registro…»** porta gli articoli giudicati nello storico
del soggetto (vedi [`REGISTRO_SOGGETTI.md`](REGISTRO_SOGGETTI.md)).

| Livello | Domanda | Valori |
|---|---|---|
| per articolo | Riguarda il soggetto? | Sì · Omonimo · Non citato · Incerto |
| per articolo | Notizia avversa per il soggetto? | Sì · No · Incerto |
| per caso | Categorie FATF corrette | elenco FATF (vuoto = nessuna) |
| per caso | Ruolo del soggetto | Autore/indagato · Vittima · Solo menzionato · Non determinabile |
| per caso | Esito corretto | Escalation (I livello) · Chiusura |
| per caso | Caso affidabile | includi nel dataset |

- **Affidabile** = giudizio completo e certo: esito, ruolo e, per ogni articolo, entrambe le
  risposte senza «Incerto». Se manca qualcosa la scheda **non salva**: evidenzia in rosso gli
  articoli e i campi incompleti («Manca: notizia avversa?»), porta al primo e riassume nel
  piè di pagina cosa manca per numero di articolo; l'evidenziazione si aggiorna mentre
  completi. Senza la spunta il caso si salva come **bozza** (non entra nel dataset). L'API
  applica la stessa regola e risponde nello stesso modo («articolo 2 (testata): notizia
  avversa?»).
- Un'etichetta per caso **per revisore**: due revisori sullo stesso caso permettono di
  misurare l'accordo tra revisori.
- La colonna **Etichetta** mostra *affidabile* / *bozza*; la barra in alto mostra
  l'avanzamento (obiettivo 100–200 casi affidabili).

La predizione del sistema **per articolo** («citato / non citato») non è mostrata nel
modulo, per non influenzare il giudizio: il confronto lo fa lo script.

### Come rispondere

La legenda sopra gli articoli e i suggerimenti sui pulsanti (al passaggio del mouse)
riportano queste definizioni:

| Domanda | Risposta | Significato |
|---|---|---|
| Riguarda il soggetto? | Sì | l'articolo parla proprio di questo soggetto |
| | Omonimo | parla di un'altra persona o azienda con lo stesso nome |
| | Non citato | il soggetto non è nominato |
| Notizia avversa per il soggetto? | Sì | attribuisce al soggetto reati, indagini, accuse, condanne, sanzioni o legami con ambienti criminali |
| | No | il soggetto è vittima, testimone o parte lesa, o è solo citato; anche se l'articolo non lo riguarda |
| entrambe | Incerto | non si può stabilire: il caso resta una bozza |

- Con **Omonimo** o **Non citato** la seconda risposta si imposta da sé su **No** (se non
  l'avevi già data); se poi torni a «Sì» viene tolta, così non resta un «No» non scelto.
- Le risposte si comportano come pulsanti di scelta: si cambiano ma un secondo clic sulla
  stessa non la cancella.
- *Esempio:* giornalista o imprenditore **vittima** di intimidazioni → «Riguarda il
  soggetto?» **Sì**, «Notizia avversa?» **No**, ruolo **Vittima**; di norma l'esito corretto è
  **Chiusura**.

Alcune combinazioni sospette mostrano un **suggerimento** (non blocca il salvataggio): ruolo
Vittima o Solo menzionato con esito Escalation; Escalation senza alcun articolo avverso;
Chiusura con un articolo pertinente e avverso. Se la scelta è voluta (es. rischio di
infiltrazione, notizie note ma non trovate dal sistema), spiegala nelle **note**.

## Duplicati: un caso per soggetto

Più alert dello stesso soggetto (screening ripetuti) **non sono casi indipendenti**: nel
dataset ne basta uno, altrimenti gli stessi errori contano più volte e gli intervalli di
confidenza risultano ottimisti. Stesso soggetto = stesso CF/P.IVA, oppure (se manca) stesso
tipo e stesso nome scritto in modo diverso («ACME S.r.l.» = «Acme srl»); omonimi con CF
diversi restano distinti.

- Pagina **Alert**: il chip **×N** accanto al soggetto; **«Solo soggetti con più alert»**
  li raggruppa; **«Seleziona i duplicati»** tiene per ogni soggetto il caso già nel
  dataset (altrimenti il più recente) e seleziona gli altri.
- **«Elimina…»** (o il cestino nella scheda): motivo obbligatorio (*duplicato* / *errato*)
  e nota facoltativa; articoli ed etichette del caso vengono eliminati. Serve un ruolo di
  `ALERT_DELETE_ROLES` (default `["amministratore"]`); ogni cancellazione resta nell'audit.
  Gli alert già pubblicati **restano in SAS VI**: la console elenca gli ID da chiudere là.
- Nella scheda, marcando *affidabile* un secondo caso dello stesso soggetto compare un avviso.
- Il report indica i **soggetti distinti** e avvisa se sono meno dei casi.

## Tre accortezze perché i numeri siano credibili

1. **Non solo escalation.** Se si etichettano solo i casi che il sistema ha segnalato, si
   misura la precisione ma **non i falsi negativi** (notizie avverse che il sistema ha
   perso). Etichetta anche casi `AUTO_CHIUSO` ed `ESITO_INCOMPLETO`, e qualche soggetto con
   notizie avverse note (per un caso chiuso senza articoli: «Esito corretto» = Escalation se
   sai che le notizie esistono). La barra mostra la distribuzione per esito del sistema e
   avvisa se si stanno etichettando solo escalation.
2. **Etichetta l'articolo, non solo l'alert**: è lì che sbagliano riconoscimento del
   soggetto e omonimia.
3. **Dati personali.** Le etichette riguardano persone reali (anche dati giudiziari, art. 10
   GDPR): restano nel sistema di record; l'**export** è riservato ai ruoli di
   `DATASET_EXPORT_ROLES` (default `["amministratore"]`) e omette CF/P.IVA, non necessari
   alla valutazione. Conservazione e uso solo per la misura della qualità.

## Export e valutazione

Console → **Esporta dataset (NDJSON)** (solo casi affidabili), oppure
`GET /api/labels/export?solo_affidabili=true`. Una riga per etichetta: giudizio del
revisore + predizione del sistema (esito, categorie, metodo di classificazione, ruoli
negli articoli e flag PEP per la persona fisica, e per ogni articolo `mentioned` /
`mention_match`).

```bash
python scripts/evaluate_labels.py dataset-casi-AAAAMMGG.ndjson          # report leggibile
python scripts/evaluate_labels.py dataset-casi-AAAAMMGG.ndjson --json   # per altri strumenti
python scripts/evaluate_labels.py dataset-casi-AAAAMMGG.ndjson --tutti  # anche le bozze
```

Il report dà, con **intervallo di confidenza al 95%** (con pochi casi le percentuali
oscillano molto) e con il numero di **soggetti distinti**:

- **riconoscimento del soggetto** (per articolo): precisione e richiamo, anche per tipo di
  corrispondenza (`nome_cognome`, `denominazione`, `denominazione_breve`, `cf_piva`), con
  l'elenco degli errori;
- **categorie FATF** (per caso): precisione e richiamo, per categoria, e quante categorie
  per caso mettono sistema e revisore (molte categorie = richiamo alto, precisione bassa);
- **esito**: accordo, **falsi negativi** (da escalation ma chiusi — l'errore più grave),
  falsi positivi, casi non decisi dal sistema, con l'**elenco dei casi sbagliati** (ruolo
  indicato dal revisore e categorie del sistema);
- tutto **per metodo di classificazione** (LLM / parole chiave) e l'accordo tra revisori.

## Rivalutazione con la versione attuale

Il report misura la predizione **salvata a suo tempo**. Per sapere come si comporta la
versione di oggi sugli stessi casi — e misurare ogni correzione prima di metterla in uso —
si ripassano gli articoli già salvati (snapshot, nessuna nuova ricerca) nella pipeline
attuale: riconoscimento del soggetto, classificazione LLM, AMI, esito.

```bash
docker compose -f docker-compose.dev.yml up -d --build worker-scraping   # dopo un aggiornamento
docker compose -f docker-compose.dev.yml exec -T worker-scraping \
    python replay.py > rivalutazione.ndjson                  # --tutti: anche le bozze
python scripts/evaluate_labels.py rivalutazione.ndjson
```

Il report mette a confronto **prima** e **dopo** (riconoscimento, categorie, categorie per
caso, esito, categorie cambiate) e poi il dettaglio della versione attuale. Anche gli alert
creati prima del salvataggio delle predizioni ottengono così il riconoscimento per articolo.

- Serve l'LLM: se non risponde la rivalutazione si ferma (a parole chiave non misurerebbe
  il sistema reale). A temperatura 0 le risposte possono comunque variare di poco.
- I casi senza articoli salvati restano invariati; uno snapshot mancante viene saltato.
- Il file contiene dati personali come l'export (senza CF/P.IVA): stesse cautele.

## Limiti

- Gli alert creati prima di questa versione non hanno le predizioni per articolo
  (`mentioned` = null): per il riconoscimento del soggetto contano solo i casi nuovi.
- La valutazione misura il sistema **sui casi etichettati**: se il campione è sbilanciato
  (vedi accortezza 1) lo sono anche i numeri.

## API

| Metodo | Percorso | Note |
|---|---|---|
| GET | `/api/alerts/{id}/label` | etichetta del revisore corrente (null se assente) |
| PUT | `/api/alerts/{id}/label` | crea/aggiorna; 422 se incompleta ma marcata affidabile |
| DELETE | `/api/alerts/{id}/label` | elimina la propria etichetta |
| GET | `/api/labels` | casi etichettati dal revisore corrente |
| GET | `/api/labels/stats` | avanzamento (tutti i revisori), anche per esito del sistema |
| GET | `/api/labels/export` | NDJSON; ruoli `DATASET_EXPORT_ROLES` |
| GET | `/api/alerts/{id}/related` | stesso soggetto in altri casi, miei giudizi sugli stessi articoli, registro |
| POST | `/api/alerts/delete` | elimina alert duplicati/errati; ruoli `ALERT_DELETE_ROLES` |
| GET | `/api/labels/replay` | interno (token di servizio): input della rivalutazione |
