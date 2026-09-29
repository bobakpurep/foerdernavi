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
from .sources import fdb, eu_sedia, dsee, scraper

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


def merge(base, new):
    """Höher priorisierte Quelle gewinnt; geprüfte Handwerte bleiben erhalten."""
    by = {norm(e["t"]) + "|" + e.get("r", ""): e for e in base}
    for e in new:
        k = norm(e["t"]) + "|" + e.get("r", "")
        old = by.get(k)
        if old and PRIO.get(old.get("quelle"), 0) > PRIO.get(e.get("quelle"), 0):
            for f in ("url", "offiziell", "text", "stand"):   # neuere Links/Texte übernehmen
                if e.get(f) and not old.get(f):
                    old[f] = e[f]
            continue
        by[k] = e
    return list(by.values())


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
    report["ende"] = datetime.now().isoformat(timespec="seconds")
    report["gesamt"] = len(data)
    if os.environ.get("FN_KOMPAKT"):   # z. B. GitHub: Repository klein halten, Originaltexte stehen auf den verlinkten Seiten
        data = [{k: v for k, v in e.items() if k != "text"} for e in data]
    (ROOT / "data" / "programme.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    LOG.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", choices=["fdb", "eu", "dsee"])
    ap.add_argument("--probe-url")
    ap.add_argument("--fdb-file")
    ap.add_argument("--nur")
    a = ap.parse_args()
    if a.probe == "fdb":
        fdb.fetch(probe=True, export_path=a.fdb_file); return 0
    if a.probe == "eu":
        eu_sedia.fetch(probe=True); return 0
    if a.probe == "dsee":
        dsee.fetch(probe=True); return 0
    if a.probe_url:
        scraper.probe(a.probe_url); return 0
    print(json.dumps(run(a.fdb_file, a.nur), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
