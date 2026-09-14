# Installare `sas-vi-integration`

Questa skill vive nel repo in **`.claude/skills/sas-vi-integration/`** → è già una
**skill di progetto**: viene caricata automaticamente nelle sessioni Claude Code su
QUESTO repo (in una sessione nuova; l'elenco skill si fissa all'avvio). Per usarla anche
in **altri progetti** installala come skill personale.

## Skill personale (tutti i progetti)

```bash
# dalla root del repo (o adatta il percorso sorgente)
mkdir -p ~/.claude/skills
cp -r .claude/skills/sas-vi-integration ~/.claude/skills/sas-vi-integration
```

Inizia una nuova sessione Claude Code: la skill compare tra quelle disponibili e viene
caricata quando un compito riguarda SAS VI, oppure la richiami con `/sas-vi-integration`.
Per aggiornarla, ricopia la cartella (sovrascrivendo), oppure installa il file `.skill`.

## Nota sull'ambiente web (effimero)
Nelle sessioni Claude Code **sul web** il container è effimero: `~/.claude` non
sopravvive tra sessioni. Il repo (`.claude/skills/…`) resta la **fonte durevole**: come
skill di progetto è sempre disponibile qui; per le skill personali su web reinstalla dal
repo o dal file `.skill`.

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
