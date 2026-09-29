"""Förderdatenbank der DSEE (foerderdatenbank.d-s-e-e.de) – Webseiten-Auslesung.

Struktur geprüft am 29.09.2026 (Seiten p53 und foerderprogramme/umwelt-schecks):
  Listenseiten: /, /p2 … /pN ("Seite X von N"), ca. 25 Einträge je Seite, gesamt ~1.325 Einträge.
  Je Eintrag: Überschrift h2, Link auf /institutionen/…, Kurztext, Link "Mehr Informationen" -> /foerderprogramme/<slug>,
  darüber Regionen als Listenpunkte ("Bundesweit", "In Nordrhein-Westfalen").
  Detailseite: h1, Beschreibung, Abschnitte "Zielgruppen/Bedingungen", "Hinweise zur Antragstellung/Bewerbung",
  Felder mit Beschriftung: "Regionen:", "Engagementbereiche:", "Max. Fördersumme:", "Eigenmittel benötigt:",
  "Bewerbungsfrist:", "Vorzeitiger Maßnahmebeginn:", danach Institution mit E-Mail, Webseite, Telefon.
Die Auslesung arbeitet mit Beschriftungen und Linkmustern statt CSS-Klassen, damit Designänderungen sie nicht brechen.
Standardmäßig AUS (sources.yaml / Redaktionsbereich): vor Aktivierung Freigabe der DSEE einholen (§§ 87a ff. UrhG).
"""
import re
from datetime import date
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from ..common import PoliteSession, keywords, THEMEN, LAENDER, slug

BASE = "https://foerderdatenbank.d-s-e-e.de/"
LABELS = ["Regionen:", "Engagementbereiche:", "Max. Fördersumme:", "Eigenmittel benötigt:", "Bewerbungsfrist:",
          "Vorzeitiger Maßnahmebeginn:", "E-Mail", "Webseite", "Telefon"]
BEREICHE = {"Bauten und Denkmalschutz": "denkmal", "Bildung": "bildung", "Digitalisierung": "digital",
            "Kinder und Jugendliche": "jugend", "Kultur, Medien und Musik": "kultur", "Soziales": "soziales",
            "Sport und Bewegung": "sport", "Umwelt-/Naturschutz, Klimaschutz und Tierschutz": "umwelt",
            "Wissenschaft und Forschung": "forschung", "Migration": "soziales", "Entwicklungszusammenarbeit": "international",
            "Engagement für gesellschaftlichen Zusammenhalt/ Demokratie": "demokratie"}
MONATE = {"Januar": 1, "Februar": 2, "März": 3, "April": 4, "Mai": 5, "Juni": 6, "Juli": 7, "August": 8,
          "September": 9, "Oktober": 10, "November": 11, "Dezember": 12}


def parse_list(html, page_url):
    soup = BeautifulSoup(html, "lxml")
    items = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/foerderprogramme/" not in href or "Mehr Informationen" not in a.get_text():
            continue
        box = a
        for _ in range(6):  # nächster Container mit Überschrift
            box = box.parent
            if box is None or box.find(["h2", "h3"]):
                break
        if box is None:
            continue
        h = box.find(["h2", "h3"])
        inst = box.find("a", href=re.compile(r"/institutionen/"))
        regions = [li.get_text(" ", strip=True) for li in box.find_all("li")]
        items.append({"titel": h.get_text(" ", strip=True) if h else "", "detail": urljoin(page_url, href),
                      "geber": inst.get_text(" ", strip=True) if inst else "", "regionen": regions})
    total = None
    m = re.search(r"Seite\s+\d+\s+von\s+(\d+)", soup.get_text(" "))
    if m:
        total = int(m.group(1))
    return items, total


def fields_from_text(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out, cur = {}, None
    for l in lines:
        if l in LABELS or l.rstrip(":") + ":" in LABELS and l.endswith(":"):
            cur = l.rstrip(":")
            out.setdefault(cur, [])
            continue
        if cur:
            if l.startswith("©") or l in ("Impressum", "Datenschutzerklärung"):
                cur = None
                continue
            out[cur].append(l)
            if cur in ("Max. Fördersumme", "Eigenmittel benötigt", "Vorzeitiger Maßnahmebeginn", "Telefon"):
                cur = None
    return out


def parse_detail(html):
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    text = soup.get_text("\n")
    f = fields_from_text(text)
    body = []
    if h1:
        for sib in h1.find_all_next(["p", "li"]):
            t = sib.get_text(" ", strip=True)
            if not t or t.rstrip(":") + ":" in LABELS:
                break
            body.append(t)
            if sum(len(b) for b in body) > 1500:
                break
    return {"titel": h1.get_text(" ", strip=True) if h1 else "", "text": " ".join(body), "felder": f,
            "links": [a["href"] for a in soup.find_all("a", href=True) if a.get_text(strip=True).startswith("Link zur")]}


def money(v):
    m = re.search(r"([\d.]+)(?:,\d+)?\s*€", v or "")
    return int(m.group(1).replace(".", "")) if m else None


def frist(vals):
    for v in vals or []:
        m = re.search(r"(\d{1,2})\.\s*(%s)\s*(\d{4})" % "|".join(MONATE), v)
        if m:
            return f"{m.group(3)}-{MONATE[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return (vals or ["laufend"])[0]


def to_entry(item, det):
    f = det["felder"]
    reg = f.get("Regionen", []) or item["regionen"]
    codes = {LAENDER.get(r.replace("In ", "").strip().lower()) for r in reg}
    codes.discard(None)
    r = "DE" if (not codes or any("Bundesweit" in x for x in reg) or len(codes) > 1) else codes.pop()
    em = (f.get("Eigenmittel benötigt") or [""])[0].lower()
    ea = 0 if em.startswith("nein") else None
    mx = money((f.get("Max. Fördersumme") or [""])[0])
    th = sorted({BEREICHE[b] for b in f.get("Engagementbereiche", []) if b in BEREICHE}) or keywords(det["text"], THEMEN)
    hin = det["text"][:450]
    if em.startswith("ja"):
        hin = "Eigenmittel erforderlich (Höhe prüfen). " + hin
    return {"id": "dsee-" + slug(item["detail"].rstrip("/").rsplit("/", 1)[-1]), "t": det["titel"] or item["titel"],
            "g": item["geber"] or "siehe DSEE", "e": "Stiftung", "r": r, "z": ["verein", "kirche"], "th": th, "a": "zuschuss",
            "rz": "nein", "q": 100 if ea == 0 else None, "ea": ea, "max": mx, "frist": frist(f.get("Bewerbungsfrist")),
            "url": (det["links"] or [item["detail"]])[0], "urlOk": True, "quellseite": item["detail"], "hin": hin,
            "kirche": "unklar", "quelle": "scrape", "stand": date.today().isoformat(),
            "lizenz": "Daten: Förderdatenbank der DSEE – Nutzung nur mit Freigabe"}


def fetch(cfg=None, probe=False):
    cfg = cfg or {}
    s = PoliteSession(delay=cfg.get("delay", 4))
    max_pages = cfg.get("max_pages", 60)
    out, page, total = [], 1, None
    while True:
        url = BASE if page == 1 else f"{BASE}p{page}"
        items, t = parse_list(s.get(url).text, url)
        total = total or t
        for it in items:
            try:
                out.append(to_entry(it, parse_detail(s.get(it["detail"]).text)))
            except Exception as ex:
                print("  übersprungen:", it["detail"], ex)
            if probe:
                print(out[-1] if out else "kein Eintrag")
                return []
        page += 1
        if not items or page > max_pages or (total and page > total):
            break
    return out
