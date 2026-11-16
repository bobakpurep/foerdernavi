"""Importlauf: aktivierte Quellen holen, mit Startdaten zusammenführen, data/programme.json schreiben.

  python -m importer.run                         # kompletter Lauf
  python -m importer.run --probe fdb|eu|dsee     # Quelle testen, nichts speichern
  python -m importer.run --probe-url URL         # Seitenstruktur einer neuen Website ansehen
  python -m importer.run --fdb-file export.zip   # FDB aus lokaler Datei oder entpacktem Ordner
Cron (täglich 4:30):  30 4 * * * cd /srv/fordernavi && .venv/bin/python -m importer.run
"""
import argparse, json, os, re, sys, traceback
from datetime import datetime
from pathlib import Path
import yaml
from .sources import fdb, eu_sedia, dsee, scraper, pvog, national, oparl, kommunen
from . import linkcheck

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "importer" / "sources.yaml"
LOG = ROOT / "data" / "import.log.json"
PRIO = {"geprueft": 5, "teilgeprueft": 4, "import": 3, "scrape": 2, "meldung": 1, "platzhalter": 0}


def load_cfg():
    return yaml.safe_load(CFG.read_text(encoding="utf-8")) or {}


def save_cfg(cfg):
    CFG.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def norm(t):
    return re.sub(r"[^a-z0-9äöüß]+", "", (t or "").lower())


STOP = {"förderung", "foerderung", "im", "rahmen", "des", "der", "die", "von", "zur", "zum", "für", "programm", "programms", "und"}


def key(t):
    return " ".join(w for w in re.findall(r"[a-zäöüß0-9]+", (t or "").lower()) if w not in STOP)


def merge(base, new):
    """Höher priorisierte Quelle gewinnt. Dubletten: gleicher Titel, Alias (Feld 'alias' in den Grunddaten)
    oder sehr ähnlicher Titel (≥ 92 % Übereinstimmung) bei gleicher Region."""
    import difflib
    by = {key(e["t"]) + "|" + e.get("r", ""): e for e in base}
    for e in base:
        for a in e.get("alias", []):
            by.setdefault(key(a) + "|" + e.get("r", ""), e)
    basis = [e for e in base if e.get("quelle") in ("geprueft", "teilgeprueft")]
    for e in new:
        k = key(e["t"]) + "|" + e.get("r", "")
        old = by.get(k)
        if old is None:
            kt = key(e["t"])
            for b in basis:
                if b.get("r") == e.get("r") and difflib.SequenceMatcher(None, kt, key(b["t"])).quick_ratio() >= 0.92 \
                        and difflib.SequenceMatcher(None, kt, key(b["t"])).ratio() >= 0.92:
                    old = b
                    break
        if old and PRIO.get(old.get("quelle"), 0) > PRIO.get(e.get("quelle"), 0):
            for f in ("offiziell", "stand"):
                if e.get(f) and not old.get(f):
                    old[f] = e[f]
            old.setdefault("auch_in", []).append(e.get("src") or e.get("quelle"))
            continue
        by[k] = e
    seen, out = set(), []
    for e in by.values():
        if id(e) not in seen:
            seen.add(id(e))
            out.append(e)
    return out


def run(fdb_file=None, only=None):
    cfg = load_cfg()
    data = json.loads((ROOT / "data" / "programme.seed.json").read_text(encoding="utf-8"))
    jobs = []
    if cfg.get("fdb", {}).get("enabled") and (not only or only == "fdb"):
        jobs.append(("fdb", "Förderdatenbank des Bundes", lambda: fdb.fetch(export_path=fdb_file)))
    if cfg.get("eu_sedia", {}).get("enabled") and (not only or only == "eu_sedia"):
        jobs.append(("eu_sedia", "EU Funding & Tenders", lambda: eu_sedia.fetch(max_pages=cfg["eu_sedia"].get("max_pages", 20))))
    if cfg.get("dsee", {}).get("enabled") and (not only or only == "dsee"):
        jobs.append(("dsee", "DSEE-Förderdatenbank", lambda: dsee.fetch(cfg["dsee"])))
    if cfg.get("pvog", {}).get("enabled") and (not only or only == "pvog"):
        jobs.append(("pvog", "Verwaltungsleistungen (PVOG)", lambda: pvog.fetch(cfg["pvog"])))
    if cfg.get("kommunen", {}).get("enabled") and (not only or only == "kommunen"):
        jobs.append(("kommunen", "Städte, Gemeinden und Kreise (Websites)", lambda: kommunen.fetch(cfg["kommunen"])))
    if cfg.get("frankreich", {}).get("enabled") and (not only or only == "frankreich"):
        jobs.append(("frankreich", "Frankreich: Aides-territoires", lambda: national.fetch_fr(cfg["frankreich"])))
    if cfg.get("spanien", {}).get("enabled") and (not only or only == "spanien"):
        jobs.append(("spanien", "Spanien: BDNS", lambda: national.fetch_es(cfg["spanien"])))
    if cfg.get("oparl", {}).get("enabled") and (not only or only == "oparl"):
        jobs.append(("oparl", "Ratsinformationssysteme (OParl)", lambda: oparl.fetch(cfg["oparl"])))
    for sc in cfg.get("scrape") or []:
        if sc.get("enabled") and (not only or only == sc["name"]):
            jobs.append((sc["name"], sc["name"], lambda sc=sc: scraper.fetch(sc)))
    report = {"start": datetime.now().isoformat(timespec="seconds"), "quellen": []}
    old = {}
    if (ROOT / "data" / "programme.json").exists():   # bei Fehler alte Einträge der Quelle behalten
        for e in json.loads((ROOT / "data" / "programme.json").read_text(encoding="utf-8")):
            old.setdefault(e.get("src", ""), []).append(e)
    for key, name, job in jobs:
        try:
            got = job()
            for e in got:
                e["src"] = key
            data = merge(data, got)
            report["quellen"].append({"quelle": name, "ok": True, "anzahl": len(got)})
        except Exception as ex:
            data = merge(data, old.get(key, []))
            report["quellen"].append({"quelle": name, "ok": False, "fehler": str(ex)[:300], "alte_behalten": len(old.get(key, []))})
            traceback.print_exc()
    if linkcheck.faellig():
        try:
            lc = linkcheck.run()
            report["quellen"].append({"quelle": "Linkprüfung Grunddaten", "ok": True, "anzahl": lc["geprueft"], "kaputt": len(lc["kaputt"])})
        except Exception as ex:
            report["quellen"].append({"quelle": "Linkprüfung Grunddaten", "ok": False, "fehler": str(ex)[:200]})
    report["ende"] = datetime.now().isoformat(timespec="seconds")
    report["gesamt"] = len(data)
    # "seit": Datum, an dem ein Eintrag erstmals im Bestand war (für "Neu hinzugefügt" und den Newsfeed)
    heute = datetime.now().date().isoformat()
    seit_alt = {}
    if (ROOT / "data" / "programme.json").exists():
        try:
            seit_alt = {e["id"]: e.get("seit") for e in json.loads((ROOT / "data" / "programme.json").read_text(encoding="utf-8"))}
        except Exception:
            seit_alt = {}
    erstlauf = not seit_alt
    for e in data:
        e["seit"] = seit_alt.get(e["id"]) or (e.get("stand") if erstlauf else heute) or heute
    if os.environ.get("FN_KOMPAKT"):   # z. B. GitHub: Repository klein halten, Originaltexte stehen auf den verlinkten Seiten
        data = [{k: v for k, v in e.items() if k != "text"} for e in data]
    (ROOT / "data" / "programme.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    LOG.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", choices=["fdb", "eu", "dsee", "pvog", "fr", "es", "oparl", "kommunen"])
    ap.add_argument("--probe-url")
    ap.add_argument("--fdb-file")
    ap.add_argument("--nur")
    a = ap.parse_args()
    if a.probe == "fdb":
        fdb.fetch(probe=True, export_path=a.fdb_file); return 0
    if a.probe == "eu":
        eu_sedia.fetch(probe=True); return 0
    if a.probe == "kommunen":
        kommunen.fetch(load_cfg().get("kommunen"), probe=True); return 0
    if a.probe == "fr":
        national.fetch_fr(load_cfg().get("frankreich"), probe=True); return 0
    if a.probe == "es":
        national.fetch_es(load_cfg().get("spanien"), probe=True); return 0
    if a.probe == "oparl":
        oparl.fetch(load_cfg().get("oparl"), probe=True); return 0
    if a.probe == "pvog":
        pvog.fetch(load_cfg().get("pvog"), probe=True); return 0
    if a.probe == "dsee":
        dsee.fetch(probe=True); return 0
    if a.probe_url:
        scraper.probe(a.probe_url); return 0
    print(json.dumps(run(a.fdb_file, a.nur), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
