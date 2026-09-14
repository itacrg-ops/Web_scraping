# SVI — far comparire l'enrichment (FATF, motivazione, risk, disposition) sull'alert

Guida operativa **lato SVI** per rendere **visibili** nell'alert i campi che il
publisher invia nell'`enrichment` dell'alerting event. È configurazione di
amministrazione del dominio (non codice). Collegata a: [`SVI_LIVE_STATUS.md`](SVI_LIVE_STATUS.md),
[`SVI_DOMAIN_ADVERSE_MEDIA.md`](SVI_DOMAIN_ADVERSE_MEDIA.md).

## Perché serve (il principio)

Nell'alerting event (flat) inviamo:

```json
{ "jsonLayout": "flat",
  "alertingEvents": [ { "score": 82, "alertTypeCode": "strategy_default", … } ],
  "enrichment":     [ { "alertingEventId": "…",
                        "risk_level": "ALTO",
                        "fatf_categories": "Corruption & Bribery; Money Laundering",
                        "disposition": "ESCALATION_I_LIVELLO",
                        "rationale": "Categorie FATF: … • AMI = 82" } ] }
```

- **L'AMI si vede** perché è il campo **core `score`** dell'alert (sempre mostrato).
- **L'`enrichment` si vede SOLO se ogni sua chiave = un ATTRIBUTO definito** nel modello
  alert del dominio. Se l'attributo non esiste, SVI **accetta** l'evento (HTTP 201) ma
  **non mostra** quel campo. È esattamente il caso attuale di `fatf_categories`/`rationale`.

Obiettivo: definire nel dominio gli attributi con **gli stessi nomi** che inviamo (o
rimappare i nomi via `.env`, vedi §5), così i valori compaiono nella scheda/griglia alert.

## Scorciatoia consigliata (chiedila all'Admin)

Il tuo Admin SVI ha già fatto funzionare un campo enrichment nell'esempio che ti ha
dato: **`categoria_tender`**. Quindi nel vostro ambiente **esiste già il punto esatto**
dove si definiscono questi attributi. La via più rapida e sicura:

> «Dove è definito `categoria_tender` (in quale schermata/oggetto)? Devo creare lì gli
> attributi analoghi per il dominio Adverse Media.»

Replica per i nostri campi ciò che è stato fatto per `categoria_tender`. Se preferisci
farlo da solo, segui i passi sotto.

## Campi da creare (nomi e tipi)

Usa **esattamente** questi nomi (case-sensitive): combaciano con i default del publisher
(`SVI_ENRICH_KEY_*`), così non serve toccare il `.env`. Inviamo tutti i valori come
**stringa**, quindi definiscili come **String/Text**.

| Nome attributo (Name) | Tipo SVI | Contenuto inviato | Priorità |
|---|---|---|---|
| `risk_level` | String | `ALTO` / `MEDIO` / `BASSO` | alta |
| `fatf_categories` | String (testo) | categorie unite: `"A; B; C"` | alta |
| `rationale` | String **lungo** / Text | motivazione (driver dell'AMI), fino a ~1000 char | alta |
| `disposition` | String | es. `ESCALATION_I_LIVELLO` | media |
| `ami_score` | String | `"82"` (ridondante: c'è già il core `score`) | bassa/opz. |
| `source` | String | `adverse-media-screening` (provenienza) | opzionale |

Note:
- **`fatf_categories`**: le inviamo come **una stringa** con separatore `"; "`. Se preferisci
  un attributo **multi-valore/lista**, dimmelo: cambio il publisher per inviare una lista.
- **`ami_score`**: puoi ometterlo (l'AMI è già il core `score`). Se lo vuoi anche in
  enrichment e definisci l'attributo come **numerico**, avvisami: oggi lo invio come stringa.
- **`rationale`**: usa un tipo **testo lungo** (la motivazione può essere una frase).

## Passi (UI amministrazione SVI)

> Le etichette esatte variano tra versioni (SVI 10.x vs Viya 2025.xx). Usa i **nomi delle
> funzioni**; il riferimento è l'*Administrator's Guide* della tua versione.

1. **Accedi** all'app **Manage Investigate and Search** → area **Administration** con
   profilo amministratore.
2. **Apri il modello alert del dominio Adverse Media** (`domainId = d_42843825`). A seconda
   della versione è sotto: *Alerts → Domains →* (il tuo dominio) *→* configurazione
   **Alert Type / Alert Modeling / attributi dell'oggetto alert**. È lo stesso posto dove
   sono definiti i campi che compaiono nell'**Alert Grid**. (In caso di dubbio: è dove è
   definito `categoria_tender` — vedi scorciatoia sopra.)
3. **Aggiungi un attributo** per ogni riga della tabella §Campi: imposta **Name** = il nome
   esatto (`risk_level`, `fatf_categories`, `rationale`, `disposition`) e **tipo** = String/Text.
   (La *Label* può essere in chiaro, es. «Categorie FATF», «Motivazione»: è solo l'etichetta
   mostrata; ciò che deve combaciare è il **Name**.)
4. **Rendi visibili** i nuovi attributi:
   - aggiungili alle **colonne dell'Alert Grid** (per vederli nella lista alert), e/o
   - alla **scheda di dettaglio** dell'alert (Page Builder / Manage Pages).
5. **Salva** e, se la tua versione lo richiede, **ri-deploya la strategia/il dominio**.

## Verifica

1. Rilancia uno screening **con un soggetto/`screening_id` nuovo** (per evitare la dedup
   idempotente: stesso screening = stesso `alertingEventId` = nessun nuovo alert).
2. Apri l'alert in coda `queue_3264317`: nella scheda/griglia devono ora comparire
   `risk_level`, `fatf_categories`, `rationale`, `disposition` (oltre all'AMI = score).
3. Se un campo ancora non si vede: il **Name** dell'attributo non combacia byte-per-byte con
   la chiave inviata → correggi il Name in SVI **oppure** allinea il publisher con
   `SVI_ENRICH_KEY_*` (§5).

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
