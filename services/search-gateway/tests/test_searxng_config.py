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


def test_version_is_pinned() -> None:
    # con :latest la build riusava un'immagine vecchia già scaricata (motori rotti)
    assert re.search(r"^FROM\s+searxng/searxng@sha256:[0-9a-f]{64}\s*$", _read("Dockerfile"), re.M)


def test_json_format_and_engines() -> None:
    settings = _read("settings.yml")
    formats = re.search(r"^\s*formats:\s*\n((?:\s+-\s*\w+\s*\n)+)", settings, re.M)
    assert formats and re.search(r"-\s*json\b", formats.group(1)), settings
    block = re.search(r"- name: il post\n((?:\s{4}.*\n)+)", settings)
    assert block and "disabled: false" in block.group(1)
    assert "- name: ansa" not in settings                    # errori HTTP: resta spento
    remove = re.search(r"remove:\s*\n((?:\s+-\s*[^\n]+\n)+)", settings)
    assert remove and "startpage" in remove.group(1)          # CAPTCHA


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")
    print("TUTTI OK")
