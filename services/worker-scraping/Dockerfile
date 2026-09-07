# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

WORKDIR /app

COPY requirements.txt .
# Dipendenze runtime di Chromium headless (Debian Bookworm). NON usiamo
# `playwright install --with-deps`: la sua lista include pacchetti font dai nomi
# obsoleti (ttf-unifont, ttf-ubuntu-font-family) non più presenti in Bookworm, e
# fa fallire la build. Installiamo solo le librerie .so necessarie all'avvio
# headless: niente screenshot → i font sono superflui (ne teniamo uno valido).
# Il browser (~150 MB) va in /opt/pw-browsers, leggibile da appuser.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
      libdrm2 libxcb1 libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 \
      libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
      libcairo2 libasound2 libglib2.0-0 libxshmfence1 fonts-liberation \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r requirements.txt \
 && playwright install chromium \
 && chmod -R a+rx /opt/pw-browsers

COPY . .

RUN useradd -r -u 10001 appuser
USER appuser

CMD ["python", "worker.py"]
