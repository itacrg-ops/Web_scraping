# Comandi di sviluppo locale (Docker Desktop).
COMPOSE = docker compose -f docker-compose.dev.yml

.PHONY: help up up-sas down logs ps build env

help:
	@echo "make env      - crea .env da .env.example (se assente)"
	@echo "make up        - avvia l'ambiente locale (senza SAS)"
	@echo "make up-sas    - avvia includendo sas-mcp-server (richiede VIYA_ENDPOINT)"
	@echo "make down      - ferma e rimuove i container"
	@echo "make logs      - segue i log"
	@echo "make ps        - stato dei servizi"
	@echo "make build     - ricostruisce le immagini"

env:
	@test -f .env || cp .env.example .env
	@echo ".env pronto (ricordati di valorizzare le variabili AZURE_* per Foundry)"

up: env
	$(COMPOSE) up --build

up-sas: env
	$(COMPOSE) --profile sas up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build
