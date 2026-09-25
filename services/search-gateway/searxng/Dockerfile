# SearXNG per il pilota, con la configurazione del repository INCLUSA nell'immagine.
#
# Versione FISSA (2026.9.23), quella su cui è verificata la configurazione: con
# `searxng/searxng:latest` la build riusava l'immagine già scaricata, anche vecchia di
# mesi, con motori che nel frattempo si sono rotti (pagine cambiate, CAPTCHA). Per
# aggiornare: nuovo digest qui, poi `docker compose ... up -d --build searxng`.
#
# Configurazione non in /etc/searxng: l'immagine lo dichiara VOLUME e Docker Compose,
# ricreando il container, vi rimonta quello che c'era prima — il vecchio volume
# ./searxng o la configurazione di default creata al primo avvio, senza il formato JSON
# (403 al search-gateway). Sta in un percorso dell'immagine e SearXNG la legge da
# SEARXNG_SETTINGS_PATH, qualunque cosa sia montata su /etc/searxng.
FROM searxng/searxng@sha256:bcfaed4091d59f7ce85670bd701a2d0295872196dc19908a3965a8353b149f83
COPY settings.yml /usr/local/searxng/adverse-media/settings.yml
ENV SEARXNG_SETTINGS_PATH=/usr/local/searxng/adverse-media/settings.yml
