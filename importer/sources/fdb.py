"""Förderdatenbank des Bundes – offizieller Programm-Export.

Aufbau (geprüft an echten Exportdateien aus dem Projekt CorrelAid/fdb_scraper, MIT):
  * Endpunkt https://www.foerderdatenbank.de/FDB/WS/export liefert ein ZIP (~50 MB).
  * Darin je Programm ein XML unter BMWI/FDB/Content/DE/Foerderprogramm/**.xml,
    verknüpfte Dokumente unter .../Foerdergeber, .../Kontakt, .../ExternerLink.
  * Jedes XML ist eine flache Liste <property name="gsb:…">; Texte in <text> (HTML, escaped),
    Werte in <value>, Kategorien als classifiedLinkLists mit hrefs wie
    /BMWI/SiteGlobals/Categories/FDB/Foerderart/zuschuss.
Lizenz: laut FAQ der Förderdatenbank CC BY 4.0 für den Export; das Impressum nennt für die
Website-Texte CC BY-ND 4.0. Deshalb bleibt der Originaltext unverändert im Feld "text";
eigene Auswertungen stehen getrennt (q, ea, max …) und sind als automatisch markiert.
"""
import html as html_lib, io, re, tempfile, zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from ..common import PoliteSession, keywords, THEMEN, quote_from, eigenanteil_from, max_from, RZ
from datetime import date

EXPORT_URL = "https://www.foerderdatenbank.de/FDB/WS/export"
SITE = "https://www.foerderdatenbank.de"
LIZENZ = "Förderdatenbank des Bundes, BMWE (CC BY 4.0 laut FAQ)"
XLINK = "{http://www.w3.org/1999/xlink}"
CONTROL_RE = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
TAG_RE = re.compile(r"<[^>]+>")

GEBIET = {"_bundesweit": "DE", "bundesweit": "DE", "baden_wuerttemberg": "BW", "bayern": "BY", "berlin": "BE",
          "brandenburg": "BB", "bremen": "HB", "hamburg": "HH", "hessen": "HE", "mecklenburg_vorpommern": "MV",
          "de_ni": "NI", "niedersachsen": "NI", "nordrhein_westfalen": "NW", "rheinland_pfalz": "RP", "saarland": "SL",
          "sachsen": "SN", "de_st": "ST", "sachsen_anhalt": "ST", "schlesig_holstein": "SH", "schleswig_holstein": "SH",
          "thueringen": "TH"}
BERECHTIGTE = {"existenzgruenderin": "gruender", "privatperson": "privat", "unternehmen": "kmu", "kommune": "kommune",
               "oeffentliche_einrichtung": "kommune", "verband_vereinigung": "verein", "hochschule": "studierende",
               "bildungseinrichtung": "verein", "forschungseinrichtung": "kmu"}
BEREICH = {"energieeffizienz_erneuerbare_energien": "energie", "existenzgruendung_festigung": "gruendung",
           "aus_weiterbildung": "bildung", "beratung": "beratung", "digitalisierung": "digital",
           "forschung_innovation_themenoffen": "forschung", "forschung_innovation_themenspezifisch": "forschung",
           "gesundheit_soziales": "soziales", "kultur_medien_sport": "kultur", "umwelt_naturschutz": "umwelt",
           "wohnungsbau_modernisierung": "bauen", "staedtebau_stadterneuerung": "bauen", "infrastruktur": "bauen",
           "landwirtschaft_laendliche_entwicklung": "laendlich", "regionalfoerderung": "laendlich",
           "aussenwirtschaft": "international", "frauenfoerderung": "soziales", "arbeit": "bildung",
           "unternehmensfinanzierung": "gruendung", "mobilitaet": "umwelt", "smart_cities_regionen": "digital",
           "messen_ausstellungen": "international"}
UF_EXTRA = {"buergerschaftliches_engagement": "ehrenamt", "kinder_jugendliche_familien": "jugend",
            "behinderte_menschen": "inklusion", "sport_sportstaetten": "sport", "denkmalschutz_pflege": "denkmal",
            "politische_bildung": "demokratie", "lebensunterhalt_soziale_sicherung": "lebensunterhalt"}


def parse_xml(path: Path):
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        return ET.fromstring(CONTROL_RE.sub(b"", path.read_bytes()))


def plain(t):
    if not t:
        return ""
    t = html_lib.unescape(t).replace("<![CDATA[", "").replace("]]>", "")
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", t)).replace("\u00ad", "").strip()


def props(root):
    out, cls = {}, {}
    for p in root.findall("property"):
        n = p.get("name")
        t, v = p.find("text"), p.find("value")
        if t is not None:
            out[n] = plain(t.text)
        elif v is not None:
            out[n] = (v.text or "").strip()
        lists = p.find("classifiedLinkLists")
        if lists is not None:
            for ll in lists.findall("classifiedLinkList"):
                c = ll.find("classifierLinks")
                head = c.findall("link") if c is not None else []
                if not head:
                    continue
                name = head[0].get(XLINK + "href", "").rsplit("/", 1)[-1]
                le = ll.find("links")
                hrefs = [l.get(XLINK + "href", "") for l in le.findall("link")] if le is not None else []
                cls.setdefault(name, []).extend(hrefs)
    return out, cls


def slugs(hrefs):
    return [h.rsplit("/", 1)[-1] for h in hrefs]


def resolve(root_dir: Path, href: str):
    """target:/BMWI/FDB/Content/DE/Foerdergeber/B/bkm -> Dokument im Export"""
    rel = href.replace("target:", "").lstrip("/")
    p = root_dir / (rel + ".xml")
    return parse_xml(p) if p.exists() else None


def parse_export(root_dir: Path):
    root_dir = Path(root_dir)
    base = root_dir / "BMWI/FDB/Content/DE/Foerderprogramm"
    if not base.is_dir():
        raise FileNotFoundError(f"Kein Programmverzeichnis unter {base}")
    out = []
    for xml in sorted(base.rglob("*.xml")):
        doc = parse_xml(xml)
        p, cls = props(doc)
        titel = p.get("gsb:title") or ""
        if not titel or p.get("gsb:shouldNotBeIndexed") == "1":
            continue
        ende = (p.get("gsb:dateOfExpiration") or "")[:10]
        if ende and ende < date.today().isoformat():
            continue
        art_s = slugs(cls.get("Foerderart", []))
        a = ("kombination" if {"zuschuss", "darlehen"} <= set(art_s) else
             "zuschuss" if "zuschuss" in art_s else "darlehen" if "darlehen" in art_s else
             "buergschaft" if ("buergschaft" in art_s or "garantie" in art_s) else
             "beteiligung" if "beteiligung" in art_s else "zuschuss")
        gebiete = [GEBIET.get(s) for s in slugs(cls.get("Foerdergebiet", []))]
        gebiete = [g for g in gebiete if g]
        ebene_s = slugs([h for h in cls.get("Foerdergeber", []) if "/Categories/" in h])
        ebene = "EU" if "eu" in ebene_s else "Land" if "land" in ebene_s else "Bund"
        r = "EU" if ebene == "EU" else ("DE" if (not gebiete or "DE" in gebiete or len(set(gebiete)) > 1) else gebiete[0])
        geber = ""
        for h in cls.get("Foerdergeber", []) + cls.get("Foerderorganisation", []):
            if "/Content/DE/" in h:
                d = resolve(root_dir, h)
                if d is not None:
                    geber = props(d)[0].get("gsb:title", "")
                    break
        link = None
        for h in cls.get("ExternerLink", []):
            d = resolve(root_dir, h)
            if d is not None and props(d)[0].get("gsb:url"):
                link = props(d)[0]["gsb:url"]
                break
        z = sorted({BERECHTIGTE[s] for s in slugs(cls.get("Foerderberechtigte", [])) if s in BERECHTIGTE}) or ["kmu"]
        th = {BEREICH[s] for s in slugs(cls.get("Foerderbereich", [])) if s in BEREICH}
        for k, v in cls.items():
            if k.startswith("UF"):
                th |= {UF_EXTRA[s] for s in slugs(v) if s in UF_EXTRA}
        voll_ = p.get("gsb:bodyText") or ""
        kurz = p.get("gsb:summary") or p.get("gsb:teaserText") or voll_[:400]
        voll = p.get("gsb:bodyText") or ""
        q, ea = quote_from(voll), eigenanteil_from(voll)
        rel = xml.relative_to(root_dir / "BMWI").with_suffix(".html")
        out.append({"id": "fdb-" + doc.get("name", xml.stem) + "-" + r.lower(), "t": titel, "g": geber or "siehe Förderdatenbank",
                    "e": ebene, "r": r, "z": z, "th": sorted(th) or keywords(titel, THEMEN), "a": a, "rz": RZ.get(a, "ja"),
                    "q": q, "ea": ea, "max": max_from(voll), "auto": bool(q or ea), "frist": ende or "laufend",
                    "url": f"{SITE}/{rel}", "urlOk": True, "offiziell": link, "hin": kurz[:600], "text": voll[:6000],
                    "kirche": "unklar", "quelle": "import", "stand": date.today().isoformat(), "lizenz": LIZENZ})
    return out


def fetch(probe=False, export_path=None):
    """export_path: bereits entpacktes Verzeichnis oder ZIP-Datei; sonst Download."""
    if export_path and Path(export_path).is_dir():
        rows = parse_export(Path(export_path))
    else:
        data = Path(export_path).read_bytes() if export_path else PoliteSession(delay=1).get(EXPORT_URL, respect_robots=False, timeout=300).content  # offizieller Download laut FAQ
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(io.BytesIO(data)).extractall(tmp)
            rows = parse_export(Path(tmp))
    if probe:
        print(f"{len(rows)} aktive Programme. Beispiel:")
        for r in rows[:3]:
            print({k: r[k] for k in ("id", "t", "g", "e", "r", "z", "th", "a", "q", "ea", "url")})
        return []
    return rows
