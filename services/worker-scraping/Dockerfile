# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

WORKDIR /app

COPY requirements.txt .
# Playwright + Chromium con le dipendenze di sistema (browser in un percorso
# leggibile da appuser). Aumenta la dimensione dell'immagine (~400 MB): è il costo
# del render delle pagine JS (B6). Disattivabile a runtime con HEADLESS_FALLBACK=false.
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && chmod -R a+rx /opt/pw-browsers

COPY . .

RUN useradd -r -u 10001 appuser
USER appuser

CMD ["python", "worker.py"]
