"""La configurazione di SearXNG (JSON abilitato, motori) deve arrivare al servizio a
prescindere dai volumi: l'immagine dichiara /etc/searxng come VOLUME e Docker Compose,
ricreando il container, vi rimonta il mount precedente (una configurazione di default
senza JSON → 403 al search-gateway). Quindi: file copiato FUORI da /etc/searxng e
indicato a SearXNG con SEARXNG_SETTINGS_PATH.

    python services/search-gateway/tests/test_searxng_config.py
"""
from __future__ import annotations

import os
import re

HERE = os.path.join(os.path.dirname(__file__), "..", "searxng")


def _read(name: str) -> str:
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def test_settings_read_from_a_path_outside_the_volume() -> None:
    docker = _read("Dockerfile")
    copy = re.search(r"^COPY\s+settings\.yml\s+(\S+)\s*$", docker, re.M)
    env = re.search(r"^ENV\s+SEARXNG_SETTINGS_PATH=(\S+)\s*$", docker, re.M)
    assert copy and env, docker
    assert copy.group(1) == env.group(1), (copy.group(1), env.group(1))
    assert not copy.group(1).startswith("/etc/searxng"), copy.group(1)


def test_json_format_and_italian_news_engines_enabled() -> None:
    settings = _read("settings.yml")
    formats = re.search(r"^\s*formats:\s*\n((?:\s+-\s*\w+\s*\n)+)", settings, re.M)
    assert formats and re.search(r"-\s*json\b", formats.group(1)), settings
    for engine in ("ansa", "il post"):
        block = re.search(rf"- name: {engine}\n((?:\s{{4}}.*\n)+)", settings)
        assert block and "disabled: false" in block.group(1), engine


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("TUTTI OK")
