"""Nationale Förderdatenbanken anderer EU-Staaten (für den EU-weiten Einsatz).

Geprüft (30.09.2026): Es gibt die Datenbanken und öffentliche Schnittstellen –
  Frankreich: API Aides-territoires (~3.000 Hilfen von 600+ Trägern inkl. Gebietskörperschaften), api.gouv.fr/data.gouv.fr
  Spanien:    Base de Datos Nacional de Subvenciones (BDNS/SNPSAP), per Gesetz alle staatlichen, regionalen und
              kommunalen Aufrufe; API-REST seit der Reform 2023 (pap.hacienda.gob.es)
NICHT geprüft: genaue Endpunkte, Authentifizierung und Feldnamen (aus Wissen). Deshalb tolerante Auswertung
und Testmodus:  python -m importer.run --probe fr   bzw.  --probe es
Aides-territoires verlangt nach meinem Wissen einen kostenlosen API-Schlüssel -> Umgebungsvariable FN_AIDES_TERRITOIRES_TOKEN.
"""
import json, os, re
from datetime import date
from ..common import PoliteSession, keywords, THEMEN, slug

TAG = re.compile(r"<[^>]+>")


def clean(t):
    return re.sub(r"\s+", " ", TAG.sub(" ", t or "")).strip()


def pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, dict):
            for kk in ("name", "nombre", "label", "descripcion"):
                if isinstance(v.get(kk), str):
                    return v[kk]
        if isinstance(v, list) and v and isinstance(v[0], (str, dict)):
            return v[0] if isinstance(v[0], str) else pick(v[0], "name", "nombre", "label")
    return ""


def items(o):
    """Liste der Datensätze aus typischen Hüllen (results, content, data, items) ziehen."""
    if isinstance(o, list):
        return o
    for k in ("results", "content", "data", "items", "convocatorias"):
        if isinstance(o.get(k), list):
            return o[k]
    return []


def entry(cc, id_, titel, geber, text, url, frist, zielgruppe_text=""):
    blob = (titel + " " + text + " " + zielgruppe_text).lower()
    z = sorted({v for k, v in {"associa": "verein", "asociaci": "verein", "commune": "kommune", "collectivit": "kommune",
                               "ayuntamiento": "kommune", "entreprise": "kmu", "empresa": "kmu", "pyme": "kmu",
                               "particulier": "privat", "personas f": "privat", "famil": "familie"}.items() if k in blob}) or ["verein", "kmu"]
    return {"id": f"{cc.lower()}-{slug(str(id_))}", "t": clean(titel)[:240], "g": clean(geber) or "siehe Aufruf", "e": "National",
            "r": cc, "c": cc, "z": z, "th": keywords(blob, THEMEN), "a": "zuschuss", "rz": "nein", "q": None, "ea": None,
            "max": None, "frist": (frist or "")[:10] or "siehe Aufruf", "url": url, "urlOk": bool(url),
            "hin": clean(text)[:380] + " (Originalsprache; automatisch importiert)", "kirche": "unklar", "quelle": "import",
            "stand": date.today().isoformat()}


def fetch_fr(cfg=None, probe=False):
    cfg = cfg or {}
    base = cfg.get("url", "https://aides-territoires.beta.gouv.fr/api")
    token = os.environ.get("FN_AIDES_TERRITOIRES_TOKEN")
    if not token:
        raise RuntimeError("Kein API-Schlüssel (FN_AIDES_TERRITOIRES_TOKEN) – bei Aides-territoires kostenlos anfordern")
    s = PoliteSession(delay=1)
    bearer = s.post(base + "/connexion/", headers={"X-AUTH-TOKEN": token}).json().get("token")
    h = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
    out, page = [], 1
    while page <= cfg.get("max_pages", 60):
        j = s.get(base + "/aids/", params={"page": page}, headers=h, respect_robots=False).json()
        if probe:
            print(json.dumps(j, ensure_ascii=False, indent=1)[:3000]); return []
        rows = items(j)
        if not rows:
            break
        for a in rows:
            if "financ" not in json.dumps(a.get("aid_types", a.get("types", "")), ensure_ascii=False).lower() and cfg.get("nur_finanziell", True):
                continue
            out.append(entry("FR", a.get("id") or a.get("slug"), pick(a, "name", "title"), pick(a, "financers", "financers_full", "perimeter"),
                             pick(a, "description", "eligibility"), pick(a, "url", "origin_url", "application_url"),
                             pick(a, "submission_deadline"), pick(a, "targeted_audiences")))
        if not j.get("next"):
            break
        page += 1
    return out


def fetch_es(cfg=None, probe=False):
    cfg = cfg or {}
    url = cfg.get("url", "https://www.infosubvenciones.es/bdnstrans/api/convocatorias/busqueda")
    s = PoliteSession(delay=1)
    out = []
    for page in range(cfg.get("max_pages", 20)):
        j = s.get(url, params={"page": page, "pageSize": 50, "order": "fechaRecepcion", "direccion": "desc", "vpd": "GE"},
                  headers={"Accept": "application/json"}, respect_robots=False).json()
        if probe:
            print(json.dumps(j, ensure_ascii=False, indent=1)[:3000]); return []
        rows = items(j)
        if not rows:
            break
        for c in rows:
            nr = c.get("numeroConvocatoria") or c.get("codigoBDNS") or c.get("id")
            out.append(entry("ES", nr, pick(c, "descripcion", "titulo"), " / ".join(x for x in (pick(c, "nivel1"), pick(c, "nivel2"), pick(c, "nivel3")) if x),
                             pick(c, "descripcionFinalidad", "descripcion"),
                             f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias/{nr}" if nr else None,
                             pick(c, "fechaFinSolicitud", "fechaRecepcion")))
    return out
