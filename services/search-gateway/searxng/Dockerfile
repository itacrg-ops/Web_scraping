# SearXNG per il pilota, con la configurazione del repository INCLUSA nell'immagine.
# Con un volume ./searxng che arriva vuoto (Docker Desktop senza la cartella condivisa)
# SearXNG creerebbe da sé una configurazione di default senza il formato JSON, e al
# search-gateway risponderebbe 403. Copiandola nell'immagine non dipende dal volume.
FROM searxng/searxng:latest
COPY settings.yml /etc/searxng/settings.yml
