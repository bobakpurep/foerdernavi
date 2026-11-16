"""Verwaltungsleistungen aus dem Portalverbund Online-Gateway (PVOG) – Bund, Länder UND Kommunen.

Geprüft (FITKO-Doku, Stand 2026): Suchdienst öffentlich ohne Anmeldung unter
  https://pvog.fitko.net/suchdienst/api   (alte Domain pvog.fitko.de seit 01.08.2026 abgeschaltet)
  optionaler API-Key im Header 'pvog-sud-api-client-id' (Umgebungsvariable FN_PVOG_CLIENT_ID)
  Endpunkte u. a.: /v7/servicedescriptions/{ars}?q=…  (Leistungen je Gebiet und Suchbegriff)
                   /v1/servicedescriptions/suggestions/{ars}?q=…
                   /v3/locations/details?plz=…      (Ort -> Amtlicher Regionalschlüssel, ARS)
  Hinweis der Doku: nur mit dem ARS einer Gemeinde suchen.
NICHT geprüft: der genaue Aufbau der JSON-Antworten (Doku sperrt automatische Abrufe, diese Umgebung
erreicht die API nicht). Deshalb liest der Parser Titel/ID/Text feldnamen-tolerant aus.
Erster Test auf dem Server:  python -m importer.run --probe pvog
"""
import json, os, re
from datetime import date
from ..common import PoliteSession, keywords, THEMEN, slug

BASE = "https://pvog.fitko.net/suchdienst/api"
LAND = {"01": "SH", "02": "HH", "03": "NI", "04": "HB", "05": "NW", "06": "HE", "07": "RP", "08": "BW", "09": "BY",
        "10": "SL", "11": "BE", "12": "BB", "13": "MV", "14": "SN", "15": "ST", "16": "TH"}
GELD = re.compile(r"geld|zuschuss|zuschüsse|förder|beihilfe|prämie|bonus|erstattung|unterhalt|pflege|stipend|darlehen|"
                  r"zulage|vorschuss|entschädigung|leistungen für|teilhabe|kostenübernahme|befreiung|ermäßigung", re.I)
TITEL_KEYS = ("leistungsname", "leistungsbezeichnung", "bezeichnung", "title", "titel", "name")
ID_KEYS = ("lbid", "leistungId", "leistungsId", "id")
TEXT_KEYS = ("kurztext", "teaser", "volltext", "beschreibung", "description", "text")
ZIELE = {"kind": "familie", "eltern": "familie", "familie": "familie", "schwanger": "familie", "student": "studierende",
         "schüler": "studierende", "ausbildung": "studierende", "verein": "verein", "unternehm": "kmu", "gründ": "gruender",
         "selbstständ": "selbststaendig"}


def headers():
    h = {"Accept": "application/json"}
    if os.environ.get("FN_PVOG_CLIENT_ID"):
        h["pvog-sud-api-client-id"] = os.environ["FN_PVOG_CLIENT_ID"]
    return h


def text(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):   # z. B. {"de": "..."} oder {"value": "..."}
        for k in ("de", "value", "text", "name"):
            if isinstance(v.get(k), str):
                return v[k]
        return next((x for x in v.values() if isinstance(x, str)), "")
    if isinstance(v, list) and v:
        return text(v[0])
    return ""


def first(d, keys):
    low = {k.lower(): v for k, v in d.items()}
    for k in keys:
        if k.lower() in low and text(low[k.lower()]):
            return text(low[k.lower()])
    return ""


def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def find_ars(o):
    for d in walk(o):
        for k, v in d.items():
            if "ars" in k.lower() and isinstance(v, str) and re.fullmatch(r"\d{12}", v):
                return v
    return None


def leistungen(o):
    """Alle Objekte mit Titel und ID – egal wie tief verschachtelt."""
    seen = set()
    for d in walk(o):
        t, i = first(d, TITEL_KEYS), first(d, ID_KEYS)
        if t and i and i not in seen and len(t) < 250:
            seen.add(i)
            url = next((text(v) for k, v in d.items() if "url" in k.lower() and text(v).startswith("http")), None)
            yield {"id": i, "t": re.sub(r"\s+", " ", t).strip(), "text": re.sub(r"<[^>]+>|\s+", " ", first(d, TEXT_KEYS)).strip(), "url": url}


def to_entry(l, ars, ort):
    blob = (l["t"] + " " + l["text"]).lower()
    z = sorted({v for k, v in ZIELE.items() if k in blob}) or ["privat"]
    if "familie" in z and "privat" not in z:
        z.append("privat")
    a = "zuschuss" if re.search(r"zuschuss|förder|prämie|bonus", blob) else "darlehen" if "darlehen" in blob else "sozialleistung"
    return {"id": "pvog-" + slug(l["id"]), "t": l["t"], "g": "Zuständige Verwaltung (je nach Wohnort)", "e": "Verwaltung",
            "r": LAND.get(ars[:2], "DE"), "z": z, "th": keywords(blob, THEMEN), "a": a, "rz": "ja" if a == "darlehen" else "nein",
            "q": None, "ea": None, "max": None, "frist": "laufend", "url": l["url"] or "https://servicesuche.bund.de", "urlOk": bool(l["url"]),
            "hin": (l["text"][:380] or "Leistungsbeschreibung der Verwaltung.") + f" (Gefunden für {ort}; Zuständigkeit und Bedingungen in der Leistungsbeschreibung prüfen.)",
            "kirche": "unklar", "quelle": "import", "stand": date.today().isoformat(),
            "lizenz": "Portalverbund Online-Gateway (PVOG), FITKO"}


def fetch(cfg=None, probe=False, session=None):
    cfg = cfg or {}
    s = session or PoliteSession(delay=cfg.get("delay", 1))
    get = lambda path, **p: s.get(BASE + path, params=p, headers=headers(), respect_robots=False).json()  # öffentliche, dokumentierte API
    out, seen = [], set()
    for ort in cfg.get("orte", []):
        ars = ort.get("ars") or find_ars(get("/v3/locations/details", plz=ort.get("plz"), ort=ort.get("name")))
        if not ars:
            raise RuntimeError(f"Kein Regionalschlüssel für {ort} gefunden")
        for q in cfg.get("begriffe", []):
            try:
                data = get(f"/v7/servicedescriptions/{ars}", q=q)
            except Exception:
                data = get(f"/v1/servicedescriptions/suggestions/{ars}", q=q)
            if probe:
                print(f"ARS {ars}, Suchbegriff '{q}':\n", json.dumps(data, ensure_ascii=False, indent=1)[:3000])
                return []
            for l in leistungen(data):
                if l["id"] in seen or not GELD.search(l["t"]):
                    continue
                seen.add(l["id"])
                out.append(to_entry(l, ars, ort.get("name", ars)))
    return out
