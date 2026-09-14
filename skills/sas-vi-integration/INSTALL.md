# Installare `sas-vi-integration` come skill personale

Questa skill è versionata nel repo (durevole). Per usarla come **skill personale**,
disponibile in tutte le tue sessioni Claude Code, copiala nella cartella delle skill
personali della macchina dove usi Claude Code.

## Installazione (macchina locale)

```bash
# dalla root del repo (o adatta il percorso sorgente)
mkdir -p ~/.claude/skills
cp -r skills/sas-vi-integration ~/.claude/skills/sas-vi-integration
```

Riavvia Claude Code (o inizia una nuova sessione): la skill compare tra quelle
disponibili e viene caricata automaticamente quando un compito riguarda SAS VI, oppure
puoi richiamarla con `/sas-vi-integration`.

Per aggiornarla in seguito, ricopia la cartella (sovrascrivendo).

## Nota sull'ambiente web (effimero)
Nelle sessioni Claude Code **sul web** il container è effimero: `~/.claude` non
sopravvive. Il repo resta la **fonte durevole** della skill. Opzioni:
- usa la skill localmente (installazione sopra), dove `~/.claude` persiste;
- oppure, per attivarla in un repo specifico anche sul web, copiala in
  `<repo>/.claude/skills/sas-vi-integration/` (skill di progetto, versionata col repo).

## Verifica rapida
```bash
cd ~/.claude/skills/sas-vi-integration/assets/svi_core
pip install -r requirements.txt
python test_svi_core.py      # atteso: 5/5 PASS
```

## Promuoverla a plugin (team)
Se in futuro vuoi condividerla col team, la si può impacchettare come **plugin** e
distribuire via marketplace interno: la skill diventa il contenuto del plugin (nessuna
riscrittura). Chiedi pure quando serve.
