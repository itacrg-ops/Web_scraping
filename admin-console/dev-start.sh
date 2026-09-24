#!/bin/sh
# Avvio della console in sviluppo (vedi Dockerfile.dev).
# CONSOLE_SRC: sorgente montato (default /app); CONSOLE_BAKED: copia nell'immagine.
SRC="${CONSOLE_SRC:-/app}"
BAKED="${CONSOLE_BAKED:-/opt/console}"

if [ -f "$SRC/package.json" ]; then
  echo "admin-console: sorgente montato ($SRC) — le modifiche ai file si vedono subito."
  cd "$SRC" && npm install --no-audit --no-fund && exec npm run dev -- --host
fi

echo "=============================================================="
echo " admin-console: il volume ./admin-console arriva VUOTO nel container"
echo " (tipico di Docker Desktop: cartella del progetto non condivisa, oppure"
echo " 'docker compose' lanciato da un'altra cartella)."
echo " La console parte comunque dalla copia inclusa nell'immagine: funziona,"
echo " ma per vedere codice nuovo dopo un 'git pull' va ricostruita:"
echo "   docker compose -f docker-compose.dev.yml up -d --build admin-console"
echo " Per l'aggiornamento automatico: Docker Desktop -> Settings -> Resources ->"
echo " File sharing (aggiungi la cartella del progetto), poi ricrea il container."
echo "=============================================================="
cd "$BAKED" && exec npm run dev -- --host
