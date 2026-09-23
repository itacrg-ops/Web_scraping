# Dataset di valutazione — etichettatura dei casi e misura degli errori

Per sapere **quanti errori fa il sistema** (e tarare soglie e regole) servono casi reali
giudicati da chi li conosce. La console permette di etichettare i casi direttamente
nella pagina **Alert**; l'export alimenta lo script di valutazione.

## Come si etichetta un caso

Pagina **Alert** → clicca il caso: si apre la **scheda laterale** (larga quanto lo schermo,
senza scroll orizzontale). Per ogni articolo trovi testata, titolo, estratto e link, con le
due domande subito sotto; poi il giudizio sul caso. Il piè di pagina resta sempre visibile:
**Salva**, oppure **Salva e successivo** per passare al caso seguente (pulsanti ‹ › in alto per
spostarsi, Esc per chiudere; se ci sono modifiche non salvate viene chiesta conferma).
L'**esito del sistema** (AMI, categorie, motivazione) è in una sezione chiusa: aprila dopo
aver giudicato, per non farti influenzare.

| Livello | Domanda | Valori |
|---|---|---|
| per articolo | Riguarda il soggetto? | Sì · Omonimo · Non citato · Incerto |
| per articolo | Notizia avversa per il soggetto? | Sì · No · Incerto |
| per caso | Categorie FATF corrette | elenco FATF (vuoto = nessuna) |
| per caso | Ruolo del soggetto | Autore/indagato · Vittima · Solo menzionato · Non determinabile |
| per caso | Esito corretto | Escalation (I livello) · Chiusura |
| per caso | Caso affidabile | includi nel dataset |

- **Affidabile** = giudizio completo e certo: esito, ruolo e, per ogni articolo, pertinenza e
  avversità senza «Incerto». Se manca qualcosa l'API rifiuta il salvataggio e dice cosa
  manca; senza la spunta il caso si salva come **bozza** (non entra nel dataset).
- Un'etichetta per caso **per revisore**: due revisori sullo stesso caso permettono di
  misurare l'accordo tra revisori.
- La colonna **Etichetta** mostra *affidabile* / *bozza*; la barra in alto mostra
  l'avanzamento (obiettivo 100–200 casi affidabili).

La predizione del sistema **per articolo** («citato / non citato») non è mostrata nel
modulo, per non influenzare il giudizio: il confronto lo fa lo script.

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
revisore + predizione del sistema (esito, categorie, metodo di classificazione, e per ogni
articolo `mentioned` / `mention_match`).

```bash
python scripts/evaluate_labels.py dataset-casi-AAAAMMGG.ndjson          # report leggibile
python scripts/evaluate_labels.py dataset-casi-AAAAMMGG.ndjson --json   # per altri strumenti
python scripts/evaluate_labels.py dataset-casi-AAAAMMGG.ndjson --tutti  # anche le bozze
```

Il report dà, con **intervallo di confidenza al 95%** (con pochi casi le percentuali
oscillano molto):

- **riconoscimento del soggetto** (per articolo): precisione e richiamo, anche per tipo di
  corrispondenza (`nome_cognome`, `denominazione`, `denominazione_breve`, `cf_piva`), con
  l'elenco degli errori;
- **categorie FATF** (per caso): precisione e richiamo, per categoria;
- **esito**: accordo, **falsi negativi** (da escalation ma chiusi — l'errore più grave),
  falsi positivi, casi non decisi dal sistema;
- tutto **per metodo di classificazione** (LLM / parole chiave) e l'accordo tra revisori.

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
