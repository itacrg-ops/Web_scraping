# SVI — far comparire l'enrichment (FATF, motivazione, risk, disposition) sull'alert

Guida operativa **lato SVI** per rendere **visibili** nell'alert i campi che il
publisher invia nell'`enrichment`. È configurazione di **visualizzazione** del dominio
(non codice, non definizione di attributi). Collegata a: [`SVI_LIVE_STATUS.md`](SVI_LIVE_STATUS.md),
[`SVI_DOMAIN_ADVERSE_MEDIA.md`](SVI_DOMAIN_ADVERSE_MEDIA.md).

> **Accertato dai dati (dump di un alert reale).** L'enrichment è **già memorizzato**
> sull'alert nel campo **`enrichmentJson`**:
> ```json
> "enrichmentJson": { "risk_level": "BASSO",
>                     "fatf_categories": "Fraud & Financial Crime; Organized Crime; …",
>                     "rationale": "⚠ Screening ESPLORATIVO…",
>                     "disposition": "AUTO_CHIUSO", "ami_score": "25" }
> ```
> Quindi **non è un problema di dato né di metadati**: la pipeline invia tutto e SVI lo
> salva. È **solo visualizzazione** — la scheda/griglia alert non mostra i campi annidati
> in `enrichmentJson`. Non serve definire attributi né l'AdminMetadataApi.

## Il principio

- **L'AMI si vede** perché è il campo **core `score`** dell'alert (sempre mostrato).
- **La motivazione completa È GIÀ VISIBILE** nel campo core **`alertTriggerText`** (che
  contiene categorie FATF, ruolo, motivazione, calcolo AMI…): l'istruttore non è "cieco".
- I campi **strutturati** (`risk_level`, `fatf_categories`, `rationale`, `disposition`)
  vivono in `enrichmentJson`: per mostrarli come campi/colonne dedicati serve configurare
  la **pagina alert** (Page Builder) e/o le **colonne dell'Alert Grid** del dominio.

## Scorciatoia consigliata (chiedila all'Admin)

Il tuo Admin SVI ha già fatto **vedere** un campo enrichment nell'esempio che ti ha dato:
**`categoria_tender`** (stesso meccanismo: sta nell'`enrichmentJson`). Quindi nella loro UI
**esiste già una pagina alert che mostra un campo da `enrichmentJson`**. La via più rapida:

> «Come fai a mostrare `categoria_tender` (che sta in `enrichmentJson`) sulla scheda/griglia
> alert? Devo mostrare allo stesso modo `risk_level`, `fatf_categories`, `rationale`,
> `disposition` per il dominio Adverse Media.»

Replica quella configurazione di pagina per i nostri campi. Se preferisci farlo da solo,
segui i passi sotto.

## Campi da mostrare (già presenti in `enrichmentJson`)

Questi campi **esistono già** dentro `enrichmentJson` di ogni alert (Name case-sensitive =
default del publisher, `SVI_ENRICH_KEY_*`). Vanno solo **portati a video** (colonna Alert
Grid e/o campo nella scheda alert), non creati. Sono tutti stringhe.

| Chiave in `enrichmentJson` | Contenuto | Dove mostrarlo |
|---|---|---|
| `risk_level` | `ALTO` / `MEDIO` / `BASSO` | griglia + dettaglio |
| `fatf_categories` | categorie unite: `"A; B; C"` | griglia + dettaglio |
| `rationale_sintesi` | **sintesi** motivazione (primo driver, breve) | **griglia** |
| `rationale` | motivazione completa (driver dell'AMI, fino a ~1000 char) | **scheda dettaglio** (widget testo lungo) |
| `fonti` | **link fonti/evidenze**: `"testata: url"` una per riga | scheda dettaglio |
| `disposition` | es. `ESCALATION_I_LIVELLO`, `AUTO_CHIUSO` | griglia |
| `ami_score` | `"25"` (ridondante: c'è già il core `score`) | opzionale |
| `source` | `adverse-media-screening` (provenienza) | opzionale |

Note:
- `fatf_categories` è **una stringa** con separatore `"; "`. Se la UI gestisce un
  multi-valore e lo preferisci, si può cambiare il publisher per inviare una lista.
- **`rationale_sintesi`** è pensato per la **griglia** (breve); il **`rationale`** completo
  per la **scheda di dettaglio** (widget testo lungo legato a `enrichmentJson.rationale`).
- **`fonti`** mostra i link come testo (cliccabilità dipende dal *cell renderer*). Per le
  evidenze **strutturate** (oggetti con url) usa i `contributingObjects`: abilita
  `SVI_SEND_CONTRIBUTING_OBJECTS=true` e configura la sezione "related/oggetti contribuenti"
  della pagina alert.

## Passi (UI di visualizzazione SVI)

> Le etichette esatte variano tra versioni. L'obiettivo non è definire attributi (i dati ci
> sono in `enrichmentJson`), ma **mostrarli**. Due posti: l'**Alert Grid** (colonne della
> lista) e la **scheda di dettaglio** dell'alert (menu *Pages*).

### A) Alert Grid — colonne della lista (procedura confermata)
Nella **Strategy** del dominio (`Alerts → Domains/Strategies →` la tua strategia):
1. tab **Alert Grid** → **Select fields for the alert grid…**;
2. aggiungi un campo per ciascuna chiave, con **Field Name = il percorso esatto** (minuscolo!):
   - `enrichmentJson.risk_level` · `enrichmentJson.fatf_categories` ·
     `enrichmentJson.disposition` · `enrichmentJson.rationale_sintesi` · `enrichmentJson.fonti`;
   - **Display Type** = `Text`; **Header Label** = etichetta a piacere; **Cell Renderer** = `Default`;
3. ordina con le frecce su/giù;
4. **Salva** e **deploya la strategia**; poi **ricarica** la lista alert (hard refresh).

Il **Field Name deve combaciare byte-per-byte** con la chiave in `enrichmentJson` (case
incluso — la `F` maiuscola di `Fatf_categories` è stata il classico intoppo).

### B) Scheda di dettaglio — `Pages` → Page Template `alert-detail`
⚠ **Attenzione**: sul Page Template i componenti si legano ai **field del modello alert**
(tab **Data → Fields**: Alert ID, Score, Disposition, Actionable entity…, **Alert-trigger
text**…). **`enrichmentJson.*` NON compare** in quella lista (a differenza dell'Alert Grid,
dove il *Field Name* è un path libero). Quindi:

- **Motivazione completa**: è **già sulla scheda** nel campo core **`Alert-trigger text`**
  (contiene tutta la motivazione che inviamo). Basta renderlo visibile/allargarlo (colonna
  *Scorecard*), eventualmente Title = "Motivazione". Nessun campo enrichment da aggiungere.
- **`fonti` / `rationale_sintesi` come campi separati sul dettaglio**: due strade —
  1. *(consigliata)* tienili nell'**Alert Grid** (lì `enrichmentJson.*` è bindabile);
  2. **esponili come field del modello** in **Data Objects** (nuovo field dell'oggetto alert
     con sorgente `enrichmentJson.fonti` / `enrichmentJson.rationale_sintesi`) → poi
     compaiono nella lista **Fields** e li leghi a un **Text Input** sul Page Template.
- **Evidenze strutturate / network**: tab **Data → Child Objects** (`alerting_event`,
  `alert_action`) con un componente **Grid/Child-Object Viewer**; il **Network Diagram** è già
  in pagina e si popola con entità+relazioni nel Data Hub (fase 2).

Salva la pagina (icona salva) e **Preview**.

> Se `enrichmentJson.*` non è direttamente legabile nella tua versione, la motivazione
> completa è comunque già leggibile nel campo core **`alertTriggerText`** (mostrato di
> default). L'enrichment strutturato serve soprattutto per **colonne/filtri**.

## Verifica

1. Apri un alert esistente in coda `queue_3264317` (i dati sono già in `enrichmentJson`,
   non serve rigenerarlo): nella scheda devono ora comparire i campi aggiunti.
2. Se un campo non appare: il **binding** alla chiave in `enrichmentJson` non è corretto
   (nome/percorso) → correggi il binding, oppure allinea il nome della chiave lato publisher
   con `SVI_ENRICH_KEY_*` (§5) al nome che la tua pagina si aspetta.

## §5 — In alternativa: rimappare i nomi lato publisher

Se in SVI esistono già attributi con nomi diversi (o preferisci nomi in italiano), non
serve rinominarli: allinea il publisher ai nomi reali nel `.env` e ricrea il container.

```dotenv
SVI_ENRICH_KEY_FATF=categorieFatf
SVI_ENRICH_KEY_RATIONALE=motivazione
SVI_ENRICH_KEY_RISK=livelloRischio
SVI_ENRICH_KEY_DISPOSITION=disposizione
```
```powershell
docker compose -f docker-compose.dev.yml up -d --force-recreate svi-publisher
```

## In alternativa alla UI: script via API dei metadati

`services/svi-publisher/scripts/svi_metadata.py` crea gli attributi via API. **Nota:** i
metadati **non** stanno in un servizio "admin-metadata" a sé — vivono nei servizi già in
uso: **alert type** sotto `/svi-alert`, **object type** (entità) sotto `/svi-datahub`. Lo
script è **discovery-first** (parte dai **link HATEOAS** dei due servizi, che espongono gli
endpoint reali) e **dry-run** finché non passi `--apply`; per non indovinare lo schema
**clona la forma di un attributo esistente** (es. `categoria_tender`). I tipi si indicano
con il **percorso completo** (es. `/svi-alert/alertTypes/<id>`). Eseguilo dove l'app raggiunge Viya:

```powershell
$svi = "docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python"

# 1) discovery: LINK reali di /svi-datahub e /svi-alert + collezioni di tipi (annota i percorsi)
& $svi scripts/svi_metadata.py
# 2) localizza un attributo che GIÀ funziona: dice tipo+percorso e forma (stampa la riga --template)
& $svi scripts/svi_metadata.py --find categoria_tender
# 3) dry-run: clona la forma di categoria_tender sul tipo Adverse Media (percorsi completi)
& $svi scripts/svi_metadata.py --type /svi-alert/alertTypes/<idAdverseMedia> `
       --template categoria_tender --template-type /svi-alert/alertTypes/<idCheContieneCategoriaTender>
# 4) scrittura reale (PUT con ETag/If-Match)
& $svi scripts/svi_metadata.py --type /svi-alert/alertTypes/<idAdverseMedia> `
       --template categoria_tender --template-type /svi-alert/alertTypes/<idCheContieneCategoriaTender> --apply
```

- Il punto 1 stampa i **link** dei servizi: da lì ricavi i percorsi reali delle collezioni
  di tipi (alert type / object type). Se una collezione non è tra i candidati, passala con
  `--extra <path>`.
- `--find` (punto 2) ti dice **tipo e percorso** dove vive l'attributo enrichment e stampa
  già la riga `--template ... --template-type ...` pronta.
- Ometti `--template*` per clonare il primo attributo del tipo target.

Incolla l'output dei punti 1–2 (link dei servizi, `--find`): se la PUT dà `405` o la chiave
dell'array attributi è diversa, adatto lo script sui dati reali. Dopo la creazione, **rendi
comunque visibili** i campi in Alert Grid / scheda alert (la UI, §Passi 4).

## Cosa stiamo inviando (per confronto 1:1)

Con `SVI_SEND_ENRICHMENT=true` nel `.env`, il dry-run stampa l'envelope completo con le
chiavi/valori enrichment esatti — utile per confrontarli con gli attributi del dominio:

```powershell
docker compose -f docker-compose.dev.yml run --build --rm svi-publisher python scripts/svi_smoketest.py
```

## Riferimenti

- [SAS Visual Investigator — Administrator's Guide](https://documentation.sas.com/api/docsets/visgatorag/v_039/content/visgatorag.pdf) — *Alert Types* / *Data Object Types*
- [Visual Investigator Alerts API](https://developer.sas.com/rest-apis/svi-alert)
