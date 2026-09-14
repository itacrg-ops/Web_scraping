# SAS VI — catalogo errori (troubleshooting)

Gli errori incontrati integrando SVI, con causa e rimedio. Prima di fixare "alla cieca",
usa `scripts/svi_smoketest.py --diagnose` per isolare il campo che innesca il problema.

| Sintomo | Causa | Rimedio |
|---|---|---|
| `500 tdc.bad.request` (anche a body vuoto) | manca l'**envelope** (`jsonLayout:"flat"` + array) o il media type | usare `build_alerting_payload` di svi_core + media type versionato |
| `415 unsupported media type` | manca il suffisso `+json;version=1` | usare `svi_alertingevent_media_type` (già default) |
| `405` su `POST /svi-alert/alerts` | gli alert non si creano lì | usare `POST /svi-alert/alertingEvents` |
| `500 errorCode 1008` **senza** `alertTypeCode` | `alertTypeCode` è **obbligatorio** | valorizzare `SVI_ALERT_TYPE_CODE` |
| `500 errorCode 1008` **con** `alertTypeCode` | `alertingEventId` **duplicato** (stessa business key già pubblicata) | è idempotenza (atteso); per un alert nuovo usa una business key nuova (`--unique` nel test) |
| `400` con `DH...` su `/svi-datahub/documents` | schema documento Data Hub non allineato | l'entità **non serve** per l'alert: non caricare il documento |
| `svi_alert_id` inizia con `svi-mock-` | servizio in **mock** | `SVI_MODE=live` nel `.env` **e** ricreare il container/processo (l'env si legge all'avvio) |
| `CERTIFICATE_VERIFY_FAILED` (self-signed) | cert non fidato | demo: `SVI_VERIFY_TLS=false`; meglio: `SVI_CA_BUNDLE` col certificato del server |
| `SSL: UNEXPECTED_EOF_WHILE_READING` (handshake) | la connessione è chiusa **durante l'handshake TLS** — NON è un problema di certificato: `SVI_VERIFY_TLS=false` **non aiuta**. Cambiato ambiente = quasi sempre endpoint/rete | verifica `VIYA_ENDPOINT` (schema `https`, host/porta giusti, **niente path o porta errata/spazi/newline**); raggiungibilità (VPN/rete interna); proxy (`env \| grep -i proxy`); possibile **mTLS** (server chiede client cert) o versione TLS. Diagnosi grezza (indip. dall'app): `curl -vk https://<host>/SASLogon/oauth/token` e `openssl s_client -connect <host>:443 -servername <host>` |
| `FileNotFoundError` su CA bundle | `SVI_CA_BUNDLE` punta a file inesistente nel container | montare il cert a quel path, o usare `SVI_VERIFY_TLS=false` (demo) |
| auth `bad user` con CLI `sas-viya` | l'ambiente usa **SAML/SSO** (nessuna password locale) | usare un client registrato (`client_credentials`) o, su demo con auth locale, `sas.ec` + grant `password`; o `SVI_AUTH_MODE=token` con bearer dal browser |
| l'alert **si crea** ma l'enrichment **non si vede** (AMI sì) | l'AMI è il core `score`; l'enrichment è in `enrichmentJson`, non mostrato di default | **visualizzazione**: aggiungere i campi alla scheda alert / colonne Alert Grid (Page Builder). Vedi `onboarding.md` |
| alert con label = id/hash poco leggibile | manca `actionableEntityLabel` | popolare `SviAlert.entity_label` (es. denominazione); default = `entity_id` |

## Note di rete
Se lavori da un ambiente con egress limitato (es. una sessione agent), le chiamate verso
Viya possono essere **bloccate dalla policy di rete**: esegui gli script dalla macchina
che raggiunge Viya. Un `403/407` dal proxy o un `CERTIFICATE_VERIFY_FAILED` immediato
verso `*.sas.com` è tipicamente questo, non un bug del codice.
