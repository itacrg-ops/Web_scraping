# Configurazione Azure AI Foundry (classificazione FATF via LLM)

Abilita il percorso di classificazione **dual-LLM strutturata** al posto
dell'euristica a keyword. Vale sia in locale (service principal di sviluppo) sia
in produzione (Workload Identity keyless) — stesso codice, cambia solo la
credenziale (§10 del documento di deployment).

## 1. Prerequisiti su Azure
- Una risorsa **Azure AI Foundry / Azure OpenAI** in **region UE** (es. *Italy North*, *Sweden Central*).
- Almeno un **deployment** di un modello che supporti l'output JSON
  (`response_format: json_object`): es. `gpt-4o`, `gpt-4o-mini`, `gpt-4-turbo`.
  Per il dual-LLM puoi usarne due (primario + secondario) o lo stesso per entrambi.

Recupera i valori (sostituisci `<resource>` e `<rg>`):
```bash
# endpoint della risorsa
az cognitiveservices account show -n <resource> -g <rg> --query properties.endpoint -o tsv
# id della risorsa (serve per l'assegnazione ruolo)
az cognitiveservices account show -n <resource> -g <rg> --query id -o tsv
# nomi dei DEPLOYMENT (colonna "name" = valore per LLM_MODEL_*)
az cognitiveservices account deployment list -n <resource> -g <rg> -o table
```

## 2. Credenziale keyless (service principal di sviluppo)
`DefaultAzureCredential` in locale usa un service principal via variabili
d'ambiente (nessuna API key statica).
```bash
# crea il service principal (annota appId, password, tenant)
az ad sp create-for-rbac -n adverse-media-dev

# assegna il ruolo minimo sulla risorsa Foundry/OpenAI
az role assignment create \
  --assignee <appId> \
  --role "Cognitive Services OpenAI User" \
  --scope <resourceId>
```
> Il ruolo **Cognitive Services OpenAI User** è sufficiente per invocare i
> modelli. La propagazione dell'assegnazione può richiedere qualche minuto.

## 3. Valorizza il `.env`
```bash
AZURE_FOUNDRY_ENDPOINT=https://<resource>.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-21
LLM_MODEL_PRIMARY=<nome-deployment-primario>
LLM_MODEL_SECONDARY=<nome-deployment-secondario>   # opzionale; vuoto = single-LLM
EMBEDDING_MODEL=<nome-deployment-embedding>         # opzionale (near-duplicate futuri)

# credenziale dev (service principal) — DefaultAzureCredential la usa in locale
AZURE_TENANT_ID=<tenant>
AZURE_CLIENT_ID=<appId>
AZURE_CLIENT_SECRET=<password>
```

## 4. Riavvia i servizi interessati
```bash
docker compose -f docker-compose.dev.yml up -d --force-recreate llm-gateway worker-scraping
```

## 5. Verifica
```bash
# 1) il gateway vede l'endpoint configurato
curl -s http://localhost:8080/healthz
# -> {"status":"ok","endpoint_configured":true}

# 2) classificazione reale su un testo di prova
curl -s -X POST http://localhost:8080/v1/classify \
  -H "Content-Type: application/json" \
  -d '{"text":"La procura ipotizza reati di corruzione e riciclaggio; disposto sequestro.","dual":true}'
# -> JSON con fatf_categories, ruolo_processuale, role_analysis, severity, confidence, rationale, method:"llm_dual"
```
Puoi anche usare la UI interattiva: `http://localhost:8080/docs`.

Da qui, uno **Screening** su un articolo adverse mostrerà nell'alert l'AMI
derivato dalla **severità** del modello e i driver con *ruolo processuale*,
*Victim-Bystander* e *motivazione* (non più l'euristica: l'AMI 78 di default
sparisce).

## Troubleshooting
| Sintomo | Causa probabile | Rimedio |
|---------|-----------------|---------|
| `/healthz` → `endpoint_configured:false` | `AZURE_FOUNDRY_ENDPOINT` non impostato o container non ricreato | valorizza il `.env`, `--force-recreate llm-gateway` |
| `/v1/classify` → **503** | credenziale mancante/non valida (SP o ruolo) | verifica `AZURE_*`, assegnazione ruolo, attendi la propagazione |
| `/v1/classify` → **502** | nome deployment errato **o** modello che non supporta `json_object` | usa il nome esatto del deployment; scegli gpt-4o/4o-mini/4-turbo |
| Alert ancora con AMI 78 | la pipeline sta ancora usando l'euristica (gateway non 200) | controlla i log `worker-scraping` (`categorie via euristica`) e il gateway |

> **Compliance (locale)**: usa **solo dati sintetici / di test** verso Foundry
> da una postazione di sviluppo; l'endpoint locale è pubblico (il Private
> Endpoint è riservato alla produzione). Vedi §10.3/§10.4 del documento di deployment.
