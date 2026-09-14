"""Gestione metadati SVI (AdminMetadataApi): aggiungere gli attributi che rendono
VISIBILE l'enrichment sull'alert (risk_level, fatf_categories, rationale, disposition).

È un tool di amministrazione **discovery-first** e **dry-run di default**: da eseguire
DOVE l'app raggiunge Viya (la sessione Claude ha egress bloccato verso *.race.sas.com).
Riusa auth/TLS del publisher (SVI_AUTH_MODE, SAS_*/VIYA_ENDPOINT, SVI_VERIFY_TLS).

Le etichette/percorsi dell'AdminMetadataApi variano per versione: lo script **scopre**
il base path e le collezioni, poi per la creazione **clona la forma di un attributo
esistente** (es. `categoria_tender`) cambiando solo Name/Label — così non si indovina lo
schema JSON. Nulla viene scritto senza `--apply` (che stampa comunque prima il body).

USO TIPICO (in ordine):
  # 1) Discovery: base path + collezioni (objectTypes/domains/alertTypes)
  python scripts/svi_metadata.py

  # 2) Trova come è definito un attributo che GIÀ funziona (per clonarne la forma)
  python scripts/svi_metadata.py --find categoria_tender

  # 3) Dump della definizione del tipo su cui aggiungere gli attributi
  python scripts/svi_metadata.py --dump <typeId> --kind objectTypes

  # 4) Dry-run: costruisce i nuovi attributi clonando un template ma NON scrive
  python scripts/svi_metadata.py --type <typeId> --kind objectTypes --template <attrEsistente>

  # 5) Scrittura reale (PUT del tipo con i nuovi attributi, ETag/If-Match)
  python scripts/svi_metadata.py --type <typeId> --kind objectTypes --template <attrEsistente> --apply

Non stampa mai token/segreti.
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
# Tutti stringa/testo (il publisher invia valori stringa). L'AMI resta il core `score`.
NEW_ATTRS: list[tuple[str, str]] = [
    ("risk_level", "Livello di rischio"),
    ("fatf_categories", "Categorie FATF"),
    ("rationale", "Motivazione"),
    ("disposition", "Disposizione proposta"),
]

# Base path candidati del servizio AdminMetadataApi (variano per versione): il primo
# che risponde con dei link viene usato. Override con --base.
BASE_CANDIDATES = [
    "/svi-admin-metadata", "/svi-adminmetadata", "/sviAdminMetadata",
    "/svi-admin", "/svi-metadata",
]
# Collezioni candidate sotto il base (entity/alert type + domini).
COLLECTIONS = ["objectTypes", "alertTypes", "entityTypes", "domains"]
# Chiavi candidate che contengono l'array degli attributi in una definizione di tipo.
ATTR_KEYS = ["attributes", "fields", "properties", "columns", "attributeList"]
# Chiavi candidate del "nome" di un attributo.
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


def discover_base(c: httpx.Client, base_url: str, h: dict, override: str | None) -> str | None:
    """Trova il base path dell'AdminMetadataApi provando i candidati (o usa --base)."""
    cands = [override] if override else BASE_CANDIDATES
    for path in cands:
        r = _get(c, base_url + path.rstrip("/") + "/", h)
        if r is None:
            continue
        print(f"   [{r.status_code}] {path}/")
        if r.status_code < 400:
            try:
                j = r.json()
            except Exception:  # noqa: BLE001
                j = None
            if isinstance(j, dict) and isinstance(j.get("links"), list):
                for lk in j["links"][:40]:
                    print(f"       {str(lk.get('method','GET')):6} {str(lk.get('rel','')):24} {lk.get('href','')}")
            print("   → base AdminMetadataApi:", path)
            return path
    return None


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
    """Individua l'array degli attributi dentro la definizione di un tipo."""
    for k in ATTR_KEYS:
        v = defn.get(k)
        if isinstance(v, list):
            return v, k
    return None, None


def list_collections(c: httpx.Client, base_url: str, base: str, h: dict) -> None:
    print("\n2) COLLEZIONI (id · nome · label)")
    for coll in COLLECTIONS:
        r = _get(c, f"{base_url}{base}/{coll}?limit=100", h)
        if r is None:
            continue
        ok = r.status_code < 400
        print(f"  [{r.status_code}] {coll}")
        if not ok:
            body = (r.text or "").strip().replace("\n", " ")
            if body:
                print("        ", body[:300])
            continue
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            continue
        for it in _items(j)[:60]:
            iid = (_self_href(it) or "").rsplit("/", 1)[-1] or it.get("id")
            print(f"        {iid}  ·  name={it.get('name')}  ·  label={it.get('label')}")


def find_attribute(c: httpx.Client, base_url: str, base: str, h: dict, name: str) -> None:
    """Cerca un attributo per nome in tutti i tipi e ne stampa la forma JSON (per clonarla)."""
    print(f"\n3) FIND attributo '{name}' (per clonarne la forma)")
    for coll in ("objectTypes", "alertTypes", "entityTypes"):
        r = _get(c, f"{base_url}{base}/{coll}?limit=100", h)
        if r is None or r.status_code >= 400:
            continue
        for it in _items(r.json()):
            href = _self_href(it)
            url = (base_url + href) if href and href.startswith("/") else f"{base_url}{base}/{coll}/{it.get('id')}"
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
                    print(f"  TROVATO in {coll}/{defn.get('name') or defn.get('id')}  (array '{key}')  URL={url}")
                    print("  --- forma dell'attributo (da usare come --template) ---")
                    print(json.dumps(a, indent=2, ensure_ascii=False))
                    return
    print("  (non trovato: prova un altro nome o guarda l'output di --dump)")


def type_url(base_url: str, base: str, kind: str, type_id: str) -> str:
    if type_id.startswith("/"):
        return base_url + type_id
    return f"{base_url}{base}/{kind}/{type_id}"


def dump_type(c: httpx.Client, url: str, h: dict) -> tuple[dict | None, str | None, str | None]:
    """GET della definizione del tipo; ritorna (defn, etag, content-type)."""
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


def build_new_attributes(template: dict) -> list[dict]:
    """Clona la forma del template per ogni NEW_ATTRS, cambiando Name/Label e togliendo
    eventuali marcatori di chiave/PK/id univoco (così sono attributi normali stringa)."""
    STRIP = {"id", "key", "primaryKey", "isKey", "unique", "isUnique", "readOnly",
             "required", "identifier", "isIdentifier"}
    out = []
    for name, label in NEW_ATTRS:
        a = copy.deepcopy(template)
        for k in list(a.keys()):
            if k in STRIP:
                a.pop(k, None)
        # imposta il nome su tutte le chiavi-nome presenti nel template
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


def fetch_template_attr(c: httpx.Client, url: str, name: str, h: dict) -> dict | None:
    """Recupera la forma di un attributo (per nome) da un ALTRO tipo (es. il tipo che
    contiene `categoria_tender`), da clonare sul tipo target."""
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


def create_attrs(c: httpx.Client, url: str, h: dict, template_name: str | None,
                 apply: bool, template_attr: dict | None = None) -> None:
    print("\n4) CREATE ATTRIBUTI  (dry-run: senza --apply NON scrive)")
    defn, etag, ctype = dump_type(c, url, h)
    if not defn:
        print("  ✗ impossibile leggere la definizione del tipo (vedi sopra)."); return
    attrs, key = _find_attr_container(defn)
    if attrs is None:
        print(f"  ✗ nessun array attributi riconosciuto (chiavi provate: {ATTR_KEYS}).")
        print("    Guarda --dump e dimmi la chiave giusta: la aggiungo."); return
    existing = {_attr_name(a) for a in attrs}
    # Template della forma: 1) attributo passato da un altro tipo (--template-type),
    # 2) attributo per nome nel tipo target, 3) primo attributo del tipo target.
    tmpl = template_attr
    if tmpl is not None:
        print(f"  (forma clonata dal template-type: attributo '{_attr_name(tmpl)}')")
    elif template_name:
        tmpl = next((a for a in attrs if _attr_name(a) == template_name), None)
        if tmpl is None:
            print(f"  ✗ template '{template_name}' non presente in questo tipo. "
                  f"Attributi: {', '.join(str(_attr_name(a)) for a in attrs)}"); return
    elif attrs:
        tmpl = attrs[0]
        print(f"  (nessun --template: uso come forma il primo attributo '{_attr_name(tmpl)}')")
    if tmpl is None:
        print("  ✗ nessun attributo esistente da cui clonare la forma: passa --template."); return

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
        print("  ⚠ conflitto ETag/If-Match: rileggi (--dump) e riprova (la definizione è cambiata).")
    elif rp.status_code == 405:
        print("  ⚠ PUT non ammesso qui: l'API potrebbe volere una POST su una sotto-risorsa")
        print("    attributi. Incolla l'output di --dump e --find e adatto lo script.")


def main() -> None:
    ap = argparse.ArgumentParser(description="AdminMetadataApi SVI — attributi enrichment")
    ap.add_argument("--base", help="override base path AdminMetadataApi (es. /svi-admin-metadata)")
    ap.add_argument("--find", metavar="NAME", help="cerca un attributo esistente per nome (per clonarne la forma)")
    ap.add_argument("--dump", metavar="TYPEID", help="stampa la definizione di un tipo")
    ap.add_argument("--type", metavar="TYPEID", help="tipo su cui aggiungere gli attributi")
    ap.add_argument("--kind", default="objectTypes", help="collezione del tipo (objectTypes|alertTypes|entityTypes)")
    ap.add_argument("--template", metavar="ATTR", help="attributo esistente di cui clonare la forma")
    ap.add_argument("--template-type", metavar="TYPEID",
                    help="tipo (altro) da cui prendere --template, es. il tipo che contiene categoria_tender")
    ap.add_argument("--template-kind", default="objectTypes",
                    help="collezione del --template-type (default: objectTypes)")
    ap.add_argument("--apply", action="store_true", help="esegue davvero la PUT (default: dry-run)")
    args = ap.parse_args()

    print("SVI AdminMetadataApi ·", settings.viya_endpoint or "(endpoint vuoto!)")
    if settings.svi_ca_bundle and not os.path.exists(settings.svi_ca_bundle):
        print("ERRORE: SVI_CA_BUNDLE inesistente; usa SVI_VERIFY_TLS=false per il demo."); raise SystemExit(1)
    if not settings.viya_endpoint:
        print("ERRORE: VIYA_ENDPOINT non impostato in .env."); raise SystemExit(1)
    token = get_token()
    print("token OK (%d char)" % len(token))
    base_url = settings.viya_endpoint.rstrip("/")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with httpx.Client(verify=settings.verify_opt(), timeout=settings.svi_request_timeout) as c:
        print("\n1) DISCOVERY base AdminMetadataApi")
        base = discover_base(c, base_url, h, args.base)
        if not base:
            print("  ✗ base AdminMetadataApi non trovato tra i candidati.")
            print("    Trovalo (developer.sas.com/apis/vi → AdminMetadataApi) e passa --base <path>.")
            return
        list_collections(c, base_url, base, h)

        if args.find:
            find_attribute(c, base_url, base, h, args.find)
        if args.dump:
            print(f"\n3b) DUMP tipo '{args.dump}' ({args.kind})")
            dump_type(c, type_url(base_url, base, args.kind, args.dump), h)
        if args.type:
            tmpl_attr = None
            if args.template and args.template_type:
                tmpl_url = type_url(base_url, base, args.template_kind, args.template_type)
                tmpl_attr = fetch_template_attr(c, tmpl_url, args.template, h)
                if tmpl_attr is None:
                    print("  ✗ template dall'altro tipo non recuperato: annullo il create."); return
            create_attrs(c, type_url(base_url, base, args.kind, args.type), h,
                         args.template, args.apply, template_attr=tmpl_attr)

    if not (args.find or args.dump or args.type):
        print("\n→ Prossimo passo: `--find categoria_tender` per vedere la forma di un attributo")
        print("  che già funziona, poi `--type <id> --template <attr>` (dry-run) e infine --apply.")


if __name__ == "__main__":
    main()
