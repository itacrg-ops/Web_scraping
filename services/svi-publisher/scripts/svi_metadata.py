"""Gestione metadati SVI: aggiungere gli attributi che rendono VISIBILE l'enrichment
sull'alert (risk_level, fatf_categories, rationale, disposition).

I metadati NON stanno in un servizio "admin-metadata" a sé: vivono dentro i servizi
già in uso — **alert type** sotto `/svi-alert`, **object type** (entità) sotto
`/svi-datahub`. Questo tool è **discovery-first** (parte dai link HATEOAS dei due
servizi, che espongono gli endpoint reali) e **dry-run** finché non passi `--apply`.
Per non indovinare lo schema JSON, la creazione **clona la forma di un attributo
esistente** (es. `categoria_tender`) cambiando solo Name/Label.

Da eseguire DOVE l'app raggiunge Viya (la sessione Claude ha egress bloccato).
Riusa auth/TLS del publisher. Non stampa mai token/segreti.

USO (in ordine):
  # 1) Discovery: link reali di /svi-datahub e /svi-alert + collezioni di tipi
  python scripts/svi_metadata.py

  # 2) Trova un attributo che GIÀ funziona (dice in quale tipo/percorso vive + la forma)
  python scripts/svi_metadata.py --find categoria_tender

  # 3) Dump della definizione del tipo target (percorso COMPLETO dai passi 1–2)
  python scripts/svi_metadata.py --dump /svi-alert/alertTypes/<id>

  # 4) Dry-run: costruisce i 4 attributi clonando un template (NON scrive)
  python scripts/svi_metadata.py --type /svi-alert/alertTypes/<id> \
      --template categoria_tender --template-type /svi-alert/alertTypes/<idTemplate>

  # 5) Scrittura reale (PUT con ETag/If-Match)
  python scripts/svi_metadata.py --type /svi-alert/alertTypes/<id> \
      --template categoria_tender --template-type /svi-alert/alertTypes/<idTemplate> --apply
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app import auth  # noqa: E402
from app.config import settings  # noqa: E402

# Attributi da creare: (Name esatto = chiave enrichment inviata, Label leggibile).
NEW_ATTRS: list[tuple[str, str]] = [
    ("risk_level", "Livello di rischio"),
    ("fatf_categories", "Categorie FATF"),
    ("rationale", "Motivazione"),
    ("disposition", "Disposizione proposta"),
]

# I metadati vivono nei servizi noti. La discovery parte dai loro link HATEOAS e naviga
# gli endpoint NOTI (che rispondono) dumpandone gli item con i loro link — così si trova
# il modello alert reale senza indovinare i nomi. Include il dump di un alert esistente
# per verificare se l'enrichment è memorizzato (→ problema di dato vs visualizzazione).
KNOWN_ROOTS = ["/svi-datahub", "/svi-alert", "/svi-search"]
# Endpoint noti (confermati dal lavoro precedente): dumpiamo item + link per navigare.
PROBE = [
    "/svi-alert/domains?limit=20",
    "/svi-alert/strategies?limit=20",
    "/svi-alert/queues?limit=20",
    "/svi-alert/dispositions?limit=20",
    "/svi-alert/alertTypes?limit=20",
    "/svi-alert/alerts?limit=5",
    "/svi-datahub/documents?limit=3",
]
# Collezioni candidate per --find (i nomi variano per versione).
COLLECTION_CANDIDATES = ["/svi-alert/alertTypes", "/svi-datahub/objectTypes"]
# Chiavi enrichment che cerchiamo dentro un alert esistente (per capire se è memorizzato).
ENRICH_KEYS = ["risk_level", "fatf_categories", "rationale", "disposition", "ami_score"]
# Chiavi candidate che contengono l'array degli attributi in una definizione di tipo.
ATTR_KEYS = ["attributes", "fields", "properties", "columns", "attributeList", "dataItems"]
NAME_KEYS = ["name", "Name", "id", "columnName", "attributeName"]


def get_token() -> str:
    if settings.svi_auth_mode == "token":
        if not settings.sas_bearer_token:
            print("ERRORE: SVI_AUTH_MODE=token ma SAS_BEARER_TOKEN è vuoto"); raise SystemExit(2)
        return settings.sas_bearer_token
    url, data, headers = auth.build_oauth_request(settings)
    with httpx.Client(verify=settings.verify_opt(), timeout=settings.svi_request_timeout) as c:
        r = c.post(url, data=data, headers=headers)
        r.raise_for_status()
        return r.json()["access_token"]


def _get(c: httpx.Client, url: str, h: dict) -> httpx.Response | None:
    try:
        return c.get(url, headers=h)
    except Exception as exc:  # noqa: BLE001
        print(f"   [ERR] GET {url}: {exc}"); return None


def _items(j) -> list:
    if isinstance(j, dict):
        return j.get("items") or []
    return j if isinstance(j, list) else []


def _self_href(obj: dict) -> str | None:
    for lk in obj.get("links", []) if isinstance(obj, dict) else []:
        if lk.get("rel") == "self":
            return lk.get("href")
    return None


def _attr_name(a: dict) -> str | None:
    for k in NAME_KEYS:
        if isinstance(a, dict) and a.get(k):
            return str(a[k])
    return None


def _find_attr_container(defn: dict) -> tuple[list | None, str | None]:
    for k in ATTR_KEYS:
        v = defn.get(k) if isinstance(defn, dict) else None
        if isinstance(v, list):
            return v, k
    return None, None


def _abs(base_url: str, href: str) -> str:
    return base_url + href if href.startswith("/") else base_url + "/" + href


def _print_links(obj, indent: str = "          ") -> None:
    for lk in (obj.get("links") or []) if isinstance(obj, dict) else []:
        rel, method, href = lk.get("rel", ""), lk.get("method", "GET"), lk.get("href", "")
        # link "self" li mostriamo sintetici; gli altri (navigazione) per intero
        print(f"{indent}{str(rel):24} {str(method):5} {href}")


def discovery(c: httpx.Client, base_url: str, h: dict, extra: list[str]) -> list[str]:
    """Naviga il grafo reale dell'API: root link + endpoint noti (item con i loro link)
    + dump di un alert esistente per capire se l'enrichment è memorizzato."""
    print("\n1) ROOT dei servizi (link)")
    for root in KNOWN_ROOTS:
        r = _get(c, base_url + root + "/", h)
        if r is None:
            continue
        print(f"  [{r.status_code}] {root}/")
        try:
            _print_links(r.json(), "       ")
        except Exception:  # noqa: BLE001
            pass

    print("\n2) ENDPOINT NOTI — item + link (per navigare al modello alert)")
    alert_detail_url = None
    for path in (extra + PROBE):
        r = _get(c, base_url + path, h)
        if r is None:
            continue
        print(f"  [{r.status_code}] {path}")
        if r.status_code >= 400:
            body = (r.text or "").strip().replace("\n", " ")
            if body:
                print("        ", body[:200])
            continue
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            continue
        items = _items(j)
        for it in items[:8]:
            iid = (_self_href(it) or "").rsplit("/", 1)[-1] or (it.get("id") if isinstance(it, dict) else None)
            nm = it.get("name") if isinstance(it, dict) else None
            lb = it.get("label") if isinstance(it, dict) else None
            print(f"        - {iid}   name={nm}   label={lb}")
            _print_links(it)
        if "/alerts" in path and items and alert_detail_url is None:
            alert_detail_url = _abs(base_url, _self_href(items[0]) or "")

    if alert_detail_url:
        print("\n3) ALERT DI ESEMPIO — l'enrichment è memorizzato sull'alert?")
        rd = _get(c, alert_detail_url, h)
        if rd is not None and rd.status_code < 400:
            print("  URL:", alert_detail_url)
            txt = rd.text or ""
            try:
                print(json.dumps(rd.json(), indent=2, ensure_ascii=False)[:3000])
            except Exception:  # noqa: BLE001
                print(txt[:3000])
            found = [k for k in ENRICH_KEYS if k in txt]
            print("\n  → chiavi enrichment presenti nell'alert:", found or "NESSUNA")
            if found:
                print("     Sono MEMORIZZATE → il problema è di VISUALIZZAZIONE (pagina/Alert Grid),")
                print("     non di dato: vanno aggiunte alla scheda alert (Page Builder), non definiti attributi.")
            else:
                print("     ASSENTI → l'enrichment non risulta agganciato all'alert: o va definito")
                print("     un attributo sul tipo, o il payload va agganciato diversamente. Incolla il dump.")
        else:
            print("  (impossibile leggere il dettaglio dell'alert:",
                  rd.status_code if rd is not None else "errore", ")")
    else:
        print("\n3) Nessun alert esistente da ispezionare (crea prima un alert, poi rilancia).")
    return []


def find_attribute(c: httpx.Client, base_url: str, h: dict, name: str, collections: list[str]) -> None:
    """Cerca un attributo per nome nelle collezioni che rispondono; stampa dove vive e
    la sua forma JSON (da usare come --template + --template-type)."""
    print(f"\n3) FIND attributo '{name}'")
    searched = collections or COLLECTION_CANDIDATES
    for path in searched:
        r = _get(c, base_url + path + "?limit=200", h)
        if r is None or r.status_code >= 400:
            continue
        for it in _items(r.json()):
            href = _self_href(it) or f"{path}/{it.get('id')}"
            url = _abs(base_url, href)
            rd = _get(c, url, h)
            if rd is None or rd.status_code >= 400:
                continue
            try:
                defn = rd.json()
            except Exception:  # noqa: BLE001
                continue
            attrs, key = _find_attr_container(defn)
            for a in attrs or []:
                if _attr_name(a) == name:
                    tpath = href.split("?")[0]
                    print(f"  TROVATO in  {tpath}   (array '{key}')")
                    print(f"    → usa:  --template {name} --template-type {tpath}")
                    print("  --- forma dell'attributo (clonata dal tool) ---")
                    print(json.dumps(a, indent=2, ensure_ascii=False))
                    return
    print("  (non trovato: prova --dump sul tipo giusto, o incolla l'output del punto 1)")


def dump_type(c: httpx.Client, url: str, h: dict) -> tuple[dict | None, str | None, str | None]:
    r = _get(c, url, h)
    if r is None:
        return None, None, None
    print(f"  [{r.status_code}] {url}")
    etag = r.headers.get("ETag") or r.headers.get("Etag")
    ctype = r.headers.get("Content-Type")
    if r.status_code >= 400:
        print("        ", (r.text or "").strip()[:400]); return None, etag, ctype
    try:
        defn = r.json()
    except Exception:  # noqa: BLE001
        print("        (risposta non-JSON)"); return None, etag, ctype
    attrs, key = _find_attr_container(defn)
    print(f"        name={defn.get('name')}  label={defn.get('label')}  attrKey={key}  "
          f"#attrs={len(attrs or [])}  etag={'sì' if etag else 'no'}")
    if attrs:
        print("        attributi:", ", ".join(str(_attr_name(a)) for a in attrs))
    return defn, etag, ctype


def fetch_template_attr(c: httpx.Client, url: str, name: str, h: dict) -> dict | None:
    rd = _get(c, url, h)
    if rd is None or rd.status_code >= 400:
        print(f"  ✗ template-type non leggibile ({url})"); return None
    try:
        defn = rd.json()
    except Exception:  # noqa: BLE001
        return None
    attrs, _ = _find_attr_container(defn)
    a = next((x for x in (attrs or []) if _attr_name(x) == name), None)
    if a is None:
        print(f"  ✗ attributo '{name}' non presente nel template-type "
              f"(attributi: {', '.join(str(_attr_name(x)) for x in (attrs or []))})")
    return a


def build_new_attributes(template: dict) -> list[dict]:
    """Clona la forma del template per ogni NEW_ATTRS (cambia Name/Label; toglie i
    marcatori chiave/PK/required, così sono normali attributi stringa)."""
    STRIP = {"id", "key", "primaryKey", "isKey", "unique", "isUnique", "readOnly",
             "required", "identifier", "isIdentifier"}
    out = []
    for name, label in NEW_ATTRS:
        a = copy.deepcopy(template)
        for k in list(a.keys()):
            if k in STRIP:
                a.pop(k, None)
        for nk in NAME_KEYS:
            if nk in a:
                a[nk] = name
        if "name" not in a and "Name" not in a:
            a["name"] = name
        for lk in ("label", "Label", "displayName"):
            if lk in a:
                a[lk] = label
        if "label" not in a and "Label" not in a and "displayName" not in a:
            a["label"] = label
        out.append(a)
    return out


def create_attrs(c: httpx.Client, url: str, h: dict, template_name: str | None,
                 apply: bool, template_attr: dict | None = None) -> None:
    print("\n4) CREATE ATTRIBUTI  (dry-run: senza --apply NON scrive)")
    defn, etag, ctype = dump_type(c, url, h)
    if not defn:
        print("  ✗ impossibile leggere la definizione del tipo (vedi sopra)."); return
    attrs, key = _find_attr_container(defn)
    if attrs is None:
        print(f"  ✗ nessun array attributi riconosciuto (chiavi provate: {ATTR_KEYS}).")
        print("    Incolla l'output di --dump: aggiungo la chiave giusta."); return
    existing = {_attr_name(a) for a in attrs}
    tmpl = template_attr
    if tmpl is not None:
        print(f"  (forma clonata dal template-type: attributo '{_attr_name(tmpl)}')")
    elif template_name:
        tmpl = next((a for a in attrs if _attr_name(a) == template_name), None)
        if tmpl is None:
            print(f"  ✗ template '{template_name}' non in questo tipo. "
                  f"Attributi: {', '.join(str(_attr_name(a)) for a in attrs)}"); return
    elif attrs:
        tmpl = attrs[0]
        print(f"  (nessun --template: uso come forma il primo attributo '{_attr_name(tmpl)}')")
    if tmpl is None:
        print("  ✗ nessun attributo da cui clonare la forma: passa --template."); return

    to_add = [a for a in build_new_attributes(tmpl) if _attr_name(a) not in existing]
    already = [name for name, _ in NEW_ATTRS if name in existing]
    if already:
        print("  già presenti (saltati):", ", ".join(already))
    if not to_add:
        print("  ✓ tutti gli attributi esistono già: niente da fare."); return
    print("  nuovi attributi da aggiungere:", ", ".join(str(_attr_name(a)) for a in to_add))
    print("  --- corpo di UN nuovo attributo (anteprima) ---")
    print(json.dumps(to_add[0], indent=2, ensure_ascii=False))

    new_defn = copy.deepcopy(defn)
    new_defn[key] = list(attrs) + to_add
    if not apply:
        print("\n  (DRY-RUN) definizione risultante NON inviata. Rilancia con --apply per scrivere.")
        print(f"  PUT sarà su: {url}  (If-Match: {'ETag presente' if etag else 'nessun ETag'})")
        return

    put_h = {**h, "Content-Type": ctype or "application/json", "Accept": "application/json"}
    if etag:
        put_h["If-Match"] = etag
    print("\n  PUT", url)
    try:
        rp = c.put(url, headers=put_h, content=json.dumps(new_defn))
    except Exception as exc:  # noqa: BLE001
        print("  ✗ errore PUT:", exc); return
    print(f"  → HTTP {rp.status_code}")
    print("    ", (rp.text or "").strip()[:600])
    if rp.status_code < 300:
        print("  ✓ attributi aggiunti. Rendili visibili in Alert Grid / scheda alert, poi")
        print("    rilancia uno screening con screening_id NUOVO e verifica in coda.")
    elif rp.status_code in (409, 412):
        print("  ⚠ conflitto ETag/If-Match: rileggi (--dump) e riprova.")
    elif rp.status_code == 405:
        print("  ⚠ PUT non ammesso qui: l'API vuole forse una POST su una sotto-risorsa")
        print("    attributi. Incolla --dump e --find e adatto lo script.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Metadati SVI — attributi enrichment (svi-alert/svi-datahub)")
    ap.add_argument("--extra", action="append", default=[], metavar="PATH",
                    help="collezione di tipi aggiuntiva da sondare (dai link del punto 1), ripetibile")
    ap.add_argument("--find", metavar="NAME", help="cerca un attributo esistente per nome (per clonarne la forma)")
    ap.add_argument("--dump", metavar="PATH", help="dump della definizione di un tipo (percorso completo)")
    ap.add_argument("--type", metavar="PATH", help="tipo target su cui aggiungere gli attributi (percorso completo)")
    ap.add_argument("--template", metavar="ATTR", help="attributo esistente di cui clonare la forma")
    ap.add_argument("--template-type", metavar="PATH", help="tipo (percorso completo) da cui prendere --template")
    ap.add_argument("--apply", action="store_true", help="esegue davvero la PUT (default: dry-run)")
    args = ap.parse_args()

    print("SVI metadata ·", settings.viya_endpoint or "(endpoint vuoto!)")
    if settings.svi_ca_bundle and not os.path.exists(settings.svi_ca_bundle):
        print("ERRORE: SVI_CA_BUNDLE inesistente; usa SVI_VERIFY_TLS=false per il demo."); raise SystemExit(1)
    if not settings.viya_endpoint:
        print("ERRORE: VIYA_ENDPOINT non impostato in .env."); raise SystemExit(1)
    token = get_token()
    print("token OK (%d char)" % len(token))
    base_url = settings.viya_endpoint.rstrip("/")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with httpx.Client(verify=settings.verify_opt(), timeout=settings.svi_request_timeout) as c:
        collections = discovery(c, base_url, h, args.extra)
        if args.find:
            find_attribute(c, base_url, h, args.find, collections)
        if args.dump:
            print(f"\n3b) DUMP {args.dump}")
            dump_type(c, _abs(base_url, args.dump), h)
        if args.type:
            tmpl_attr = None
            if args.template and args.template_type:
                tmpl_attr = fetch_template_attr(c, _abs(base_url, args.template_type), args.template, h)
                if tmpl_attr is None:
                    print("  ✗ template dall'altro tipo non recuperato: annullo il create."); return
            create_attrs(c, _abs(base_url, args.type), h, args.template, args.apply, template_attr=tmpl_attr)

    if not (args.find or args.dump or args.type):
        print("\n→ Prossimo passo: `--find categoria_tender` (dice tipo+percorso e forma),")
        print("  poi `--type <path> --template categoria_tender --template-type <path>` (dry-run), infine --apply.")


if __name__ == "__main__":
    main()
