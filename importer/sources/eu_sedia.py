"""EU Funding & Tenders Portal – öffentliche Search API (SEDIA).

Endpunkt laut offizieller API-Seite der Kommission:
  POST https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=***
Details übernommen aus der quelloffenen Implementierung pipeworx-io/mcp-eu-funding-tenders (MIT):
  * Body ist multipart/form-data; JEDER Teil braucht Content-Type application/json, sonst HTTP 500.
  * type 1 = Förderaufrufe (Grants), status 31094501 = demnächst, 31094502 = offen, 31094503 = geschlossen.
  * Nur "terms"-Filter werden beachtet; Datumsbereiche nicht -> Fristen clientseitig filtern.
  * Metadatenfelder sind Listen: identifier, title, callIdentifier, callTitle, deadlineDate, status,
    frameworkProgramme (numerische ID), typesOfAction, descriptionByte.
Aus dem Container dieser Entwicklungsumgebung nicht erreichbar -> live auf dem Server testen:
  python -m importer.run --probe eu
"""
import json, re
from datetime import date
from ..common import PoliteSession, keywords, THEMEN

URL = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
STATUS = {"offen": "31094502", "demnaechst": "31094501"}
TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{}"
PROGRAMME = {"43108390": "Horizon Europe", "43252405": "LIFE", "43353764": "Erasmus+", "43251814": "Creative Europe",
             "43152860": "Digital Europe", "43251567": "Connecting Europe Facility", "43332642": "EU4Health",
             "43251589": "CERV (Bürger, Gleichstellung, Rechte, Werte)", "43251447": "AMIF", "43252476": "Binnenmarktprogramm",
             "43089234": "Innovationsfonds", "43392145": "EMFAF", "44416173": "I3", "43637601": "Pilotprojekte"}
TAG = re.compile(r"<[^>]+>")


def one(m, k):
    v = (m or {}).get(k)
    return (v[0] if isinstance(v, list) and v else v) or ""


def search(s, page, size, status_codes):
    must = [{"terms": {"type": ["1"]}}, {"terms": {"status": status_codes}}]
    parts = {"query": ("blob", json.dumps({"bool": {"must": must}}), "application/json"),
             "languages": ("blob", json.dumps(["en"]), "application/json"),
             "sort": ("blob", json.dumps({"field": "deadlineDate", "order": "ASC"}), "application/json")}
    r = s.post(URL, params={"apiKey": "SEDIA", "text": "***", "pageSize": size, "pageNumber": page},
               files=parts, headers={"Accept": "application/json"})
    j = r.json()
    if j.get("type") == "throwable":
        raise RuntimeError(j.get("message"))
    return j


def fetch(max_pages=20, page_size=50, probe=False, include_forthcoming=True):
    s = PoliteSession(delay=1.5)
    codes = [STATUS["offen"]] + ([STATUS["demnaechst"]] if include_forthcoming else [])
    heute = date.today().isoformat()
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        j = search(s, page, page_size, codes)
        res = j.get("results", [])
        if probe:
            print("Treffer gesamt:", j.get("totalResults"))
            print(json.dumps(res[:1], indent=1, ensure_ascii=False)[:3000])
            return []
        if not res:
            break
        for it in res:
            m = it.get("metadata", {})
            ident = one(m, "identifier")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            frist = one(m, "deadlineDate")[:10]
            if frist and frist < heute:
                continue
            prog = PROGRAMME.get(one(m, "frameworkProgramme"), "EU-Programm")
            titel = one(m, "title") or ident
            desc = TAG.sub(" ", one(m, "descriptionByte") or "")
            desc = re.sub(r"\s+", " ", desc).strip()
            status = "offen" if one(m, "status") == STATUS["offen"] else "demnächst"
            out.append({"id": "eu-" + ident.lower(), "t": titel, "g": f"Europäische Kommission – {prog}", "e": "EU", "r": "EU",
                        "z": ["kmu", "verein"] + (["kommune"] if "CERV" in prog or "LIFE" in prog else []),
                        "th": keywords(titel + " " + desc[:600], THEMEN) or (["forschung"] if "Horizon" in prog else []),
                        "a": "zuschuss", "rz": "nein", "q": None, "ea": None, "max": None, "frist": frist or "siehe Aufruf",
                        "url": TOPIC_URL.format(ident), "urlOk": True,
                        "hin": f"EU-Aufruf {ident} ({prog}, Status: {status}). Meist für Organisationen, oft nur im internationalen Konsortium; Förderquote je Maßnahmentyp. {desc[:350]}",
                        "kirche": "unklar", "quelle": "import", "stand": heute})
        if len(res) < page_size:
            break
    return out
