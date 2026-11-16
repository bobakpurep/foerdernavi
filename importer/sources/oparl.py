"""Kommunale Förderrichtlinien aus Ratsinformationssystemen (Standard OParl).

Viele Städte und Kreise veröffentlichen Beschlussvorlagen und Satzungen über eine offene OParl-Schnittstelle
(Beispiel geprüft: rim.ekom21.de/bad-vilbel/webservice/oparl/v1.1/..., Anbieter ekom21 betreut viele hessische Kommunen).
Der Importer durchsucht die Vorlagen ('paper') eines Gremiums nach Förderbegriffen und meldet Treffer als
ungeprüfte Hinweise mit Ort – so tauchen neue oder geänderte Vereinsförderrichtlinien automatisch auf.
Feldnamen nach OParl 1.x (name, date, mainFile.accessUrl, web, links.next); nicht gegen eine echte Instanz getestet.
"""
import re
from datetime import date, timedelta
from ..common import PoliteSession, slug

MUSTER = re.compile(r"förderrichtlinie|vereinsförderung|zuschussrichtlinie|förderprogramm|sportförderung|kulturförderung|"
                    r"jugendförderung|ehrenamtsförderung|förderung von vereinen|zuwendungsrichtlinie", re.I)


def fetch(cfg=None, probe=False):
    cfg = cfg or {}
    s = PoliteSession(delay=cfg.get("delay", 2))
    grenze = (date.today() - timedelta(days=365 * cfg.get("jahre", 3))).isoformat()
    out = []
    for q in cfg.get("quellen", []):
        body = s.get(q["body"], respect_robots=False).json()
        url, pages = body.get("paper"), 0
        while url and pages < q.get("max_pages", 30):
            j = s.get(url, respect_robots=False).json()
            pages += 1
            for p in j.get("data", []):
                name, dat = p.get("name") or "", (p.get("date") or "")[:10]
                if not MUSTER.search(name) or (dat and dat < grenze):
                    continue
                f = p.get("mainFile") or {}
                link = (f.get("accessUrl") if isinstance(f, dict) else None) or p.get("web") or p.get("id")
                out.append({"id": "oparl-" + slug(q["ort"] + "-" + (p.get("reference") or name)), "t": f"{q['ort']}: {name[:200]}",
                            "g": q.get("geber", "Stadt/Gemeinde " + q["ort"]), "e": "Kreis/Stadt", "r": q.get("land", "DE"),
                            "ort": [q["ort"]], "z": ["verein", "kirche"], "th": [], "a": "zuschuss", "rz": "nein", "q": None, "ea": None,
                            "max": None, "frist": "beim Ort erfragen", "url": link, "urlOk": bool(link),
                            "hin": f"Hinweis aus dem Ratsinformationssystem ({dat or 'Datum unbekannt'}): Vorlage zu einer möglichen Förderrichtlinie. Automatisch gefunden, Inhalt nicht geprüft – Dokument lesen oder beim Ort nachfragen.",
                            "kirche": "unklar", "quelle": "scrape", "stand": date.today().isoformat()})
                if probe:
                    print(out[-1]); return []
            url = (j.get("links") or {}).get("next")
    return out
