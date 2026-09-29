"""Gemeinsame Bausteine: höfliche HTTP-Sitzung, robots.txt, Normalisierung ins Fördernavi-Schema."""
import os, re, time, unicodedata, urllib.robotparser
from datetime import date
from urllib.parse import urlparse
import requests

USER_AGENT = "FoerdernaviBot/0.2 (+" + os.environ.get("FN_KONTAKT", "https://[ihre-domain]/impressum") + ")"  # Kontakt per Umgebungsvariable FN_KONTAKT

LAENDER = {"baden-württemberg": "BW", "bayern": "BY", "berlin": "BE", "brandenburg": "BB", "bremen": "HB",
           "hamburg": "HH", "hessen": "HE", "mecklenburg-vorpommern": "MV", "niedersachsen": "NI",
           "nordrhein-westfalen": "NW", "rheinland-pfalz": "RP", "saarland": "SL", "sachsen-anhalt": "ST",
           "sachsen": "SN", "schleswig-holstein": "SH", "thüringen": "TH"}

# Schlagwort -> Zielgruppe / Thema (Kleinbuchstaben, Teilwort-Treffer)
ZIELGRUPPEN = {"existenzgründ": "gruender", "gründer": "gruender", "privatperson": "privat", "privat": "privat",
               "unternehmen": "kmu", "kmu": "kmu", "selbstständig": "selbststaendig", "freiberuf": "selbststaendig",
               "verein": "verein", "verband": "verein", "gemeinnützig": "verein", "stiftung": "verein",
               "kommune": "kommune", "öffentliche einrichtung": "kommune", "kirche": "kirche", "religions": "kirche",
               "studier": "studierende", "schüler": "studierende"}
THEMEN = {"gründung": "gruendung", "existenzgründung": "gruendung", "energie": "energie", "heizung": "energie",
          "wohnungsbau": "bauen", "bau": "bauen", "sanierung": "bauen", "weiterbildung": "bildung", "bildung": "bildung",
          "ausbildung": "bildung", "soziales": "soziales", "familie": "soziales", "inklusion": "inklusion",
          "ehrenamt": "ehrenamt", "engagement": "ehrenamt", "jugend": "jugend", "kultur": "kultur", "heimat": "kultur",
          "sport": "sport", "umwelt": "umwelt", "natur": "umwelt", "klima": "umwelt", "demokratie": "demokratie",
          "digital": "digital", "forschung": "forschung", "innovation": "forschung", "beratung": "beratung",
          "denkmal": "denkmal", "ländlich": "laendlich", "landwirtschaft": "laendlich", "international": "international",
          "außenwirtschaft": "international"}


class PoliteSession:
    """HTTP mit robots.txt-Prüfung, Pause zwischen Abrufen und eindeutigem User-Agent."""
    def __init__(self, delay=2.0):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self._robots = {}
        self._last = 0.0

    def allowed(self, url):
        """robots.txt mit eigenem User-Agent lesen. 404 = alles erlaubt; 401/403 = Verbot (Standardverhalten)."""
        host = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(host + "/robots.txt", timeout=20)
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.status_code >= 400:
                    rp.allow_all = True
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp.allow_all = True
            self._robots[host] = rp
        return self._robots[host].can_fetch(USER_AGENT, url)

    def get(self, url, respect_robots=True, **kw):
        """respect_robots=False nur für offiziell angebotene Exporte/Schnittstellen (kein Crawling)."""
        if respect_robots and not self.allowed(url):
            raise PermissionError(f"robots.txt verbietet den Abruf: {url}")
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        r = self.s.get(url, timeout=kw.pop("timeout", 60), **kw)
        self._last = time.time()
        r.raise_for_status()
        return r

    def post(self, url, **kw):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        r = self.s.post(url, timeout=60, **kw)
        self._last = time.time()
        r.raise_for_status()
        return r


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s.encode("ascii", "ignore").decode()).strip("-")[:80]


def keywords(text, table):
    t = (text or "").lower()
    return sorted({v for k, v in table.items() if k in t})


def region(text):
    t = (text or "").lower()
    if not t or "bundesweit" in t or "deutschland" in t:
        return "DE"
    hits = [code for name, code in LAENDER.items() if name in t]
    return hits[0] if len(hits) == 1 else "DE"


def art_from(text):
    t = (text or "").lower()
    z = "zuschuss" in t or "zuwendung" in t
    d = "darlehen" in t or "kredit" in t
    if "bürgschaft" in t and not (z or d):
        return "buergschaft"
    if "beteiligung" in t and not (z or d):
        return "beteiligung"
    if z and d:
        return "kombination"
    return "darlehen" if d else "zuschuss"


RZ = {"zuschuss": "nein", "pauschale": "nein", "stipendium": "nein", "sozialleistung": "nein",
      "darlehen": "ja", "buergschaft": "ja", "beteiligung": "ja", "kombination": "teilweise"}


def quote_from(text):
    """Liest 'bis zu 80 %' heuristisch aus. Ergebnis immer als automatisch gekennzeichnet."""
    m = re.search(r"bis zu (\d{1,3})\s?(?:%|prozent)", (text or "").lower())
    return int(m.group(1)) if m and 0 < int(m.group(1)) <= 100 else None


def eigenanteil_from(text):
    m = re.search(r"eigenanteil[^.%]{0,40}?(\d{1,2})\s?(?:%|prozent)", (text or "").lower())
    return int(m.group(1)) if m else None


def max_from(text):
    m = re.search(r"(?:höchstens|bis zu|maximal)\s+([\d.,]+)\s*(mio\.?|millionen)?\s*(?:euro|eur|€)", (text or "").lower())
    if not m:
        return None
    n = float(m.group(1).replace(".", "").replace(",", "."))
    return int(n * 1_000_000) if m.group(2) else int(n)


def make_entry(*, id, titel, geber, text, gebiet="", berechtigte="", bereich="", foerderart="", url=None,
               quelle, ebene=None, lizenz=None):
    a = art_from(foerderart or text)
    q, ea = quote_from(text), eigenanteil_from(text)
    r = region(gebiet)
    e = ebene or ("EU" if "europ" in (geber or "").lower() else ("Land" if r != "DE" else "Bund"))
    return {"id": id, "t": titel.strip(), "g": (geber or "").strip() or "unbekannt", "e": e, "r": "EU" if e == "EU" else r,
            "z": keywords(berechtigte + " " + text[:400], ZIELGRUPPEN) or ["kmu"],
            "th": keywords(bereich + " " + titel, THEMEN), "a": a, "rz": RZ.get(a, "ja"),
            "q": q, "ea": ea, "max": max_from(text), "auto": bool(q or ea), "frist": None, "url": url,
            "urlOk": bool(url), "hin": re.sub(r"\s+", " ", text or "")[:420], "kirche": "unklar",
            "quelle": quelle, "stand": date.today().isoformat(), **({"lizenz": lizenz} if lizenz else {})}
