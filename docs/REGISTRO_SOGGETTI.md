# Registro dei soggetti: nomi simili, varianti e notizie confermate

Il registro (pagina **Soggetti**) è la base dell'anti-omonimia. Oltre ai dati anagrafici
**impara dalle decisioni dei revisori**: quali nomi simili sono lo stesso soggetto (varianti,
refusi) e quali no, e quali notizie sono state verificate. Queste decisioni le usa
l'Entity Resolution nei nuovi screening.

## Nomi simili prima di uno screening

Pagina **Screening** → «Cerca articoli» o «Avvia screening»: se il nome è simile a un
soggetto del registro o a uno già screenato (es. «Stropa Andrea» / «Stroppa Andrea»), la
console chiede conferma una volta per nome:

| Scelta | Effetto |
|---|---|
| **È lo stesso: usa «Stroppa Andrea»** | il modulo prende nome e dati del soggetto; «Stropa Andrea» diventa una sua **variante** |
| **È lo stesso: correggi il registro** | il soggetto del registro prende il nome inserito; il vecchio nome resta come variante |
| **È un altro soggetto** | la coppia viene ricordata come **soggetti diversi**: non verrà più proposta |
| **Prosegui con «…»** | nessuna decisione: si continua con il nome inserito |

Se il soggetto ha già degli alert, la console lo dice prima di crearne un altro (duplicato).
Lo stesso controllo vale quando si **aggiunge un soggetto** al registro: se esiste già con un
nome simile, si può registrare il nome come sua variante invece di creare un doppione.

## Soggetto già inserito

Un soggetto è **già inserito** nel registro se ha lo stesso **CF/P.IVA** (anche con un nome
scritto in altro modo) oppure lo stesso **nome** o una sua variante confermata — a meno che
un identificativo presente su entrambi sia diverso (CF/P.IVA o, per una persona, data di
nascita): è un **omonimo** e si registra a parte.

- **Aggiunta dalla pagina Soggetti**: la console mostra «Soggetto già inserito nel registro:
  «…»» e non crea il doppione (per cambiarne i dati si usa la modifica nella tabella). Con
  lo stesso nome e un CF o una data di nascita diversi propone l'omonimo con «Aggiungi
  comunque».
- **Conferma dalla scheda del caso**: se il soggetto è già nel registro il dialogo lo dice
  e, dopo la conferma, il messaggio è «Soggetto già inserito nel registro: «…» — N articoli
  confermati» (per un soggetto nuovo: «Soggetto inserito nel registro»). Se si sceglie di
  aggiungerlo ma c'è già, la console passa al soggetto esistente.
- **Import CSV**: una riga di un soggetto già inserito lo **aggiorna** (anche senza CF, per
  nome) e le celle vuote non cancellano i dati presenti; una riga scritta con una variante
  confermata non lo rinomina.

L'API applica la stessa regola: `409` «Soggetto già inserito nel registro: «…»».

## Ruoli negli articoli e PEP

Per una persona fisica il worker legge il **ruolo scritto accanto al nome** negli articoli
(«il sindaco di Latina Mario Rossi», «Mario Rossi, AD di Acme») e segnala una possibile
**PEP** (persona politicamente esposta, D.Lgs. 231/2007) se la carica è nell'elenco di
legge — dettagli in `docs/ARCHITETTURA.md` §7. Nella console:

- **Alert**: chip **PEP** accanto al nome; la scheda del caso mostra i ruoli trovati;
- **Screening**: al termine, l'esito con i ruoli e il flag PEP (e «Apri il caso»);
- **Conferma nel registro**: i ruoli sono proposti (spuntati) e diventano le **cariche**
  del soggetto; il flag **PEP** è proposto per una carica certa e in corso, e va spuntato
  a mano quando dipende da dati da verificare (sindaco: capoluogo o almeno 15.000
  abitanti; carica cessata: vale un anno). Una conferma successiva non toglie il flag;
- **Soggetti**: chip PEP e colonna «Ruolo · cariche»; entrambi modificabili, anche
  nell'aggiunta. Nel CSV: colonne `pep` (`si`/vuoto) e `cariche` (separate da `;`).

Il flag PEP non cambia l'AMI: è un'informazione per l'analista e per l'adeguata verifica.

## Nome con refuso scoperto dopo lo screening

Se il nome esatto non compare in nessun articolo ma compare un nome molto simile
(«Stropp Andrea» → gli articoli dicono «Andrea Stroppa»), il worker lo segnala nella
motivazione dell'alert e la scheda del caso mostra l'avviso con **«Ripeti lo screening»**
(modulo già compilato con il nome corretto). Il caso sbagliato si elimina poi come
**errato**. Le parole corte e comuni (Rossi/Rosso, Mario/Maria) non vengono proposte: sono
quasi sempre persone diverse.

## Conferma nel registro, a valle dell'etichettatura

Nella scheda del caso, dopo aver salvato l'etichetta: **«Conferma nel registro…»**. Gli
articoli con giudizio certo (entrambe le risposte, senza «Incerto») entrano nello **storico
verificato** del soggetto, con il giudizio sul caso (categorie, ruolo, esito):

- se il soggetto è nel registro (trovato per Entity Resolution, CF/P.IVA, nome o variante)
  la conferma va lì;
- altrimenti lo si aggiunge, **correggendo il nome** se l'alert aveva un refuso: il nome
  dell'alert diventa una variante del soggetto;
- ripetere la conferma aggiorna gli articoli già presenti (vale l'ultima).

Nella pagina **Soggetti** la colonna **Notizie** mostra le notizie confermate (con chi le ha
confermate e quando) e sotto il nome compaiono le **varianti** e i nomi **diversi**. Una
conferma sbagliata si rimuove dall'elenco.

Durante l'etichettatura il giudizio già presente nel registro compare **solo dopo** aver
risposto (etichettatura cieca), evidenziato se diverso dal proprio.

## Come le usa l'Entity Resolution

- **Varianti**: un nome uguale a una variante conta come il nome del soggetto (candidato
  forte; con il CUP dell'intervento risolve l'identità).
- **Soggetti diversi**: il soggetto non viene proposto come candidato per quel nome; lo
  screening non si ferma più in «da rivedere» per quella somiglianza.

## Audit

Nella tabella `audit_log` restano chi e quando ha: eliminato un alert (con motivo e nota),
creato, rinominato o eliminato un soggetto, deciso su un nome simile, confermato o rimosso
notizie. I dettagli contengono identificativi e motivi, non i dati del soggetto.

## API

| Metodo | Percorso | Note |
|---|---|---|
| GET | `/api/subjects/similar` | nomi simili nel registro e tra gli screening; alert già presenti. Con `cf_piva` e `data_nascita`, `registro_esatto` è il soggetto già inserito (stessa regola del 409) |
| POST | `/api/subjects/{id}/names` | decisione su un nome: `stesso` (variante) o `diverso` |
| DELETE | `/api/subjects/{id}/names/{name_id}` | annulla una decisione |
| GET | `/api/subjects/{id}/articles` | notizie confermate |
| DELETE | `/api/subjects/{id}/articles/{article_id}` | rimuove una conferma |
| POST | `/api/alerts/{id}/confirm` | conferma gli articoli del caso nel registro; `cariche` e `pep` aggiornano il soggetto; `nuovo_soggetto` dice se è stato creato |
| POST | `/api/alerts/delete` | elimina alert duplicati/errati (ruoli `ALERT_DELETE_ROLES`) |

`GET /api/subjects/registry` (interno, per l'Entity Resolution) include `alias` e `distinti`.

## Limiti

I confronti tra nomi scorrono registro e alert in memoria: adatto al pilota (migliaia di
soggetti). Con registri molto grandi serve un indice di similarità in Postgres (`pg_trgm`).
