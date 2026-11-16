"""Prüft die Links der geprüften Grunddaten (offizielle Seite + Belege) und meldet nicht erreichbare.
Läuft im Import (höchstens alle 7 Tage), Ergebnis: data/linkcheck.json und ein Eintrag im Importprotokoll."""
import json
from datetime import date, datetime
from pathlib import Path
import requests
from .common import USER_AGENT

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "linkcheck.json"


def faellig(tage=7):
    if not OUT.exists():
        return True
    try:
        last = date.fromisoformat(json.loads(OUT.read_text(encoding="utf-8"))["datum"])
        return (date.today() - last).days >= tage
    except Exception:
        return True


def check(url, s):
    try:
        r = s.head(url, allow_redirects=True, timeout=15)
        if r.status_code in (403, 405) or r.status_code >= 500:   # manche Server erlauben kein HEAD
            r = s.get(url, allow_redirects=True, timeout=20, stream=True)
        return r.status_code < 400, r.status_code
    except requests.RequestException as ex:
        return False, type(ex).__name__


def run():
    seed = json.loads((ROOT / "data" / "programme.seed.json").read_text(encoding="utf-8"))
    urls = {}
    for e in seed:
        for u in [e.get("url")] + (e.get("pruef") or {}).get("belege", []):
            if u and u.startswith("http"):
                urls.setdefault(u, []).append(e["id"])
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    kaputt = []
    for u, ids in urls.items():
        ok, code = check(u, s)
        if not ok:
            kaputt.append({"url": u, "status": str(code), "eintraege": ids})
    res = {"datum": date.today().isoformat(), "zeit": datetime.now().isoformat(timespec="seconds"), "geprueft": len(urls), "kaputt": kaputt}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
