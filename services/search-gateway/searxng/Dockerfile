# SearXNG per il pilota, con la configurazione del repository INCLUSA nell'immagine.
#
# Non in /etc/searxng: l'immagine lo dichiara VOLUME e Docker Compose, ricreando il
# container, vi rimonta quello che c'era prima — il vecchio volume ./searxng o la
# configurazione di default creata al primo avvio, senza il formato JSON (403 al
# search-gateway). La configurazione sta in un percorso dell'immagine e SearXNG la
# legge da SEARXNG_SETTINGS_PATH, qualunque cosa sia montata su /etc/searxng.
FROM searxng/searxng:latest
COPY settings.yml /usr/local/searxng/adverse-media/settings.yml
ENV SEARXNG_SETTINGS_PATH=/usr/local/searxng/adverse-media/settings.yml
