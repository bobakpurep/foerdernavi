"""Deutschlandweite Suche nach kommunalen Förderungen (Städte, Gemeinden, Landkreise).

Ablauf je Nacht:
  1. Verzeichnis aller Kommunen mit Website (alle 90 Tage neu): Wikidata (Gemeindeschlüssel + offizielle Website,
     Merkmal P856 geprüft; Merkmalsnummern P439/P440 für Gemeinde-/Kreisschlüssel aus Wissen) – Ersatzweg OpenStreetMap
     (Schlüssel de:amtlicher_gemeindeschluessel + website).
  2. Die nächsten N Kommunen (Standard 300) werden besucht: Startseite + Sitemap, Links mit Förderbegriffen werden gelesen.
  3. Seiten mit Förder-Signal werden als ungeprüfte Hinweise gespeichert (quelle "scrape", Ort = Kommune;
     bei Kreisen alle Gemeinden des Kreises als Orte, damit die Ortssuche greift).
  4. Fortschritt in data/kommunen_state.json – nach ca. 36 Nächten ist ganz Deutschland einmal durchlaufen.
Regeln: robots.txt wird beachtet, Pause zwischen Abrufen, Zeitbudget je Lauf, eindeutiger User-Agent.
Einschätzung (keine Rechtsberatung): Förderrichtlinien von Behörden sind amtliche Werke (§ 5 UrhG); kurze Auszüge mit Link sind unkritisch.
"""
import json, re, time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from ..common import PoliteSession, keywords, THEMEN, slug, quote_from, eigenanteil_from, max_from, kirche_from

ROOT = Path(__file__).resolve().parents[2]
VERZ = ROOT / "data" / "kommunen.json"
STATE = ROOT / "data" / "kommunen_state.json"
LAND = {"01": "SH", "02": "HH", "03": "NI", "04": "HB", "05": "NW", "06": "HE", "07": "RP", "08": "BW", "09": "BY",
        "10": "SL", "11": "BE", "12": "BB", "13": "MV", "14": "SN", "15": "ST", "16": "TH"}
LINK_KW = re.compile(r"förder|foerder|zuschuss|zuschuess|zuwendung|vereinsförder|solar|photovoltaik|balkonkraftwerk|steckersolar|"
                     r"dachbegr|zisterne|regenwasser|entsiegel|fassade|altbau|sanierung|klimaschutz|ehrenamt|wohnraum|"
                     r"familienförder|baukinder|kinderbonus|stadtteilfonds|kulturförder|sportförder|heimat|denkmal|energieberatung", re.I)
SKIP = re.compile(r"\.(jpg|jpeg|png|gif|zip|docx?|xlsx?|mp4|mp3)(\?|$)|/(login|suche|search|kontakt|impressum|datenschutz)", re.I)
GELD = re.compile(r"(\d[\d.]*\s?(€|euro))|zuschuss|förderhöhe|fördersatz|gefördert werden|förderfähig|zuwendung", re.I)
ANTRAG = re.compile(r"antrag|beantrag|richtlinie|antragsformular|antragsteller|bewilligung", re.I)
FRIST = re.compile(r"(?:frist|antragsfrist|bis zum|bis spätestens|einsendeschluss)\D{0,20}(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)

WD_SPARQL = "https://query.wikidata.org/sparql"
WD_QUERY = """SELECT ?item ?name ?key ?web ?typ WHERE {
  { ?item wdt:P439 ?key . BIND("gemeinde" AS ?typ) } UNION { ?item wdt:P440 ?key . BIND("kreis" AS ?typ) }
  ?item wdt:P856 ?web . FILTER NOT EXISTS { ?item wdt:P576 ?ende }
  ?item rdfs:label ?name . FILTER(LANG(?name) = "de") }"""
OVERPASS = "https://overpass-api.de/api/interpreter"
OSM_QUERY = """[out:json][timeout:900];area["ISO3166-1"="DE"][admin_level=2]->.de;
relation(area.de)["boundary"="administrative"]["admin_level"~"^(6|8)$"]["de:amtlicher_gemeindeschluessel"]["website"];out tags;"""


# ---------- Verzeichnis ----------
def verzeichnis_wikidata(s):
    r = s.get(WD_SPARQL, params={"query": WD_QUERY, "format": "json"}, headers={"Accept": "application/sparql-results+json"},
              respect_robots=False, timeout=600)
    out = {}
    for b in r.json()["results"]["bindings"]:
        key, typ = b["key"]["value"].strip(), b["typ"]["value"]
        if (typ == "gemeinde" and not re.fullmatch(r"\d{8}", key)) or (typ == "kreis" and not re.fullmatch(r"\d{5}", key)):
            continue
        out.setdefault(key, {"ags": key, "name": b["name"]["value"], "web": b["web"]["value"], "typ": typ})
    return list(out.values())


def verzeichnis_osm(s):
    r = s.post(OVERPASS, data={"data": OSM_QUERY}, timeout=900)
    out = {}
    for el in r.json().get("elements", []):
        t = el.get("tags", {})
        key = re.sub(r"\D", "", t.get("de:amtlicher_gemeindeschluessel", ""))
        if not t.get("website") or len(key) not in (5, 8):
            continue
        typ = "kreis" if t.get("admin_level") == "6" else "gemeinde"
        key = key[:5] if typ == "kreis" else key
        out.setdefault(key, {"ags": key, "name": t.get("name", key), "web": t["website"], "typ": typ})
    return list(out.values())


def verzeichnis(s, cfg):
    if VERZ.exists():
        v = json.loads(VERZ.read_text(encoding="utf-8"))
        if (date.today() - date.fromisoformat(v["stand"])).days < cfg.get("verzeichnis_tage", 90):
            return v["kommunen"]
    fehler = []
    for quelle, f in (("wikidata", verzeichnis_wikidata), ("osm", verzeichnis_osm)):
        if cfg.get("verzeichnis") and cfg["verzeichnis"] != quelle and quelle == "wikidata":
            continue
        try:
            k = f(s)
            if len(k) > 500:   # Plausibilität: Deutschland hat ~10.800 Gemeinden und ~400 Kreise
                k.sort(key=lambda x: (x["typ"] != "kreis", x["ags"]))
                VERZ.write_text(json.dumps({"stand": date.today().isoformat(), "quelle": quelle, "kommunen": k}, ensure_ascii=False), encoding="utf-8")
                return k
            fehler.append(f"{quelle}: nur {len(k)} Treffer")
        except Exception as ex:
            fehler.append(f"{quelle}: {ex}")
    if VERZ.exists():
        return json.loads(VERZ.read_text(encoding="utf-8"))["kommunen"]
    raise RuntimeError("Kein Kommunenverzeichnis: " + "; ".join(fehler))


# ---------- Seiten finden und lesen ----------
def kandidaten(s, web, max_links):
    base = web if web.startswith("http") else "https://" + web
    host = urlparse(base).netloc.replace("www.", "")
    found = {}

    def add(url, text=""):
        u = urljoin(base, url).split("#")[0]
        if urlparse(u).netloc.replace("www.", "") != host or SKIP.search(u):
            return
        score = len(LINK_KW.findall(u.lower())) * 2 + len(LINK_KW.findall(text.lower()))
        if score:
            found[u] = max(found.get(u, 0), score)

    try:
        soup = BeautifulSoup(s.get(base, timeout=20).text, "lxml")
        for a in soup.select("a[href]"):
            add(a["href"], a.get_text(" ", strip=True))
    except Exception:
        pass
    for sm in ("/sitemap.xml", "/sitemap_index.xml"):
        try:
            xml = s.get(urljoin(base, sm), timeout=20).text
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)[:3000]
            subs = [l for l in locs if l.endswith(".xml")][:5]
            for sub in subs:
                try:
                    locs += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", s.get(sub, timeout=20).text)[:3000]
                except Exception:
                    pass
            for l in locs:
                if not l.endswith(".xml"):
                    add(l)
            if locs:
                break
        except Exception:
            continue
    return [u for u, _ in sorted(found.items(), key=lambda x: -x[1])[:max_links]]


def lese(html, url):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "header", "footer", "aside"]):
        t.decompose()
    main = soup.select_one("main, article, [role=main], #content, .content") or soup.body or soup
    titel = (soup.h1.get_text(" ", strip=True) if soup.h1 else "") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))[:6000]
    return titel[:200], text


def eintrag(k, url, titel, text, orte):
    q, ea = quote_from(text), eigenanteil_from(text)
    if q is not None and ea is None and q < 100:
        ea = 100 - q
    m = FRIST.search(text)
    frist = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else "siehe Seite"
    blob = (titel + " " + text[:1500]).lower()
    z = sorted({v for kk, v in {"verein": "verein", "privat": "privat", "eigentümer": "privat", "bürger": "privat", "famili": "familie",
                                "unternehm": "kmu", "gewerbe": "kmu", "kirch": "kirche"}.items() if kk in blob}) or ["privat", "verein"]
    return {"id": f"kom-{k['ags']}-{slug(titel or url)[:50]}", "t": f"{k['name']}: {titel or 'Förderung'}", "g": k["name"],
            "e": "Kreis/Stadt", "r": LAND.get(k["ags"][:2], "DE"), "ort": orte, "z": z, "th": keywords(blob, THEMEN),
            "a": "zuschuss" if "darlehen" not in blob else "kombination", "rz": "nein", "q": q, "ea": ea, "max": max_from(text),
            "auto": True, "frist": frist, "url": url, "urlOk": True, "kirche": kirche_from(text),
            "hin": text[:380] + " (Automatisch auf der Website der Kommune gefunden – Inhalt und Aktualität nicht geprüft.)",
            "quelle": "scrape", "src": "kommunen", "stand": date.today().isoformat()}


def fetch(cfg=None, probe=False, session=None, alte=None):
    cfg = cfg or {}
    s = session or PoliteSession(delay=cfg.get("delay", 1.5))
    alle = verzeichnis(s, cfg)
    gemeinden_je_kreis = {}
    for k in alle:
        if k["typ"] == "gemeinde":
            gemeinden_je_kreis.setdefault(k["ags"][:5], []).append(k["name"])
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"pos": 0, "runde": 1}
    n = 3 if probe else cfg.get("pro_lauf", 300)
    start, ende = time.time(), time.time() + 60 * cfg.get("max_minuten", 60)
    besucht, neu = set(), []
    pos = state["pos"]
    for i in range(min(n, len(alle))):
        if time.time() > ende:
            break
        k = alle[(pos + i) % len(alle)]
        besucht.add(k["ags"])
        orte = [k["name"]] + (gemeinden_je_kreis.get(k["ags"], []) if k["typ"] == "kreis" else [])
        try:
            for url in kandidaten(s, k["web"], cfg.get("max_seiten_pro_ort", 6)):
                try:
                    titel, text = lese(s.get(url, timeout=20).text, url)
                except Exception:
                    continue
                if GELD.search(text) and ANTRAG.search(text) and LINK_KW.search(titel + " " + text[:600]):
                    neu.append(eintrag(k, url, titel, text, orte))
        except Exception as ex:
            print("  übersprungen:", k["name"], ex)
        if probe:
            print(k["name"], "→", [e["t"] for e in neu if e["g"] == k["name"]])
    if probe:
        return []
    neue_pos = (pos + len(besucht)) % len(alle)
    state.update(pos=neue_pos, runde=state.get("runde", 1) + (1 if neue_pos < pos else 0), letzter_lauf=date.today().isoformat(),
                 kommunen_gesamt=len(alle), besucht_letzter_lauf=len(besucht), dauer_min=round((time.time() - start) / 60, 1))
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    if alte is None:   # Einträge nicht besuchter Kommunen vom letzten Lauf behalten
        f = ROOT / "data" / "programme.json"
        alte = [e for e in json.loads(f.read_text(encoding="utf-8")) if e.get("src") == "kommunen"] if f.exists() else []
    behalten = [e for e in alte if e["id"].split("-")[1] not in besucht]
    seen, out = set(), []
    for e in behalten + neu:
        if e["id"] not in seen:
            seen.add(e["id"])
            out.append(e)
    return out
