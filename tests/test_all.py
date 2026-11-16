"""Tests: python -m pytest -q   (aus dem Projektordner)"""
import os, re, sys, json, tempfile, shutil
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["FN_DB"] = tempfile.mktemp(suffix=".sqlite3")
from fastapi.testclient import TestClient
from server.app import app, OUTBOX
from importer.sources import fdb, dsee

c = TestClient(app)


def test_fdb_echte_exportdateien():
    rows = fdb.fetch(export_path=ROOT / "tests/fixtures/fdb_export")
    ids = {r["id"] for r in rows}
    assert "fdb-einstiegsgeld-de" in ids
    e = next(r for r in rows if r["id"] == "fdb-einstiegsgeld-de")
    assert e["g"] == "Bundesagentur für Arbeit (BA)" and e["a"] == "zuschuss" and e["url"].startswith("https://www.foerderdatenbank.de/")


def test_dsee_parser():
    items, total = dsee.parse_list((ROOT / "tests/fixtures/dsee/liste.html").read_text(), "https://foerderdatenbank.d-s-e-e.de/p53")
    assert total == 53 and len(items) == 2
    e = dsee.to_entry(items[0], dsee.parse_detail((ROOT / "tests/fixtures/dsee/detail.html").read_text()))
    assert (e["r"], e["ea"], e["max"], e["frist"]) == ("NW", 0, 2000, "2026-09-30")


def test_startdaten_alle_mit_status():
    data = json.loads((ROOT / "data/programme.seed.json").read_text(encoding="utf-8"))
    assert all(e["quelle"] in ("geprueft", "teilgeprueft", "platzhalter") for e in data)
    assert all(e.get("pruef", {}).get("belege") for e in data if e["quelle"] == "geprueft")


def test_konto_redaktion_meldung_reset():
    a = c.post("/api/register", json={"email": "red@t.de", "password": "redaktion123"}).json()["token"]
    ha = {"Authorization": "Bearer " + a}
    assert c.get("/api/me", headers=ha).json()["rolle"] == "redaktion"
    u = c.post("/api/register", json={"email": "nutzer@t.de", "password": "nutzerpass12"}).json()["token"]
    hu = {"Authorization": "Bearer " + u}
    assert c.get("/api/admin/uebersicht", headers=hu).status_code == 403
    assert c.post("/api/meldungen", json={"titel": "Testförderung", "url": "https://example.org"}).json()["ok"]
    m = c.get("/api/admin/meldungen", headers=ha).json()[0]
    ent = {"t": "Testförderung", "g": "Stadt", "r": "NW", "ort": ["Teststadt"], "q": 80, "ea": 20}
    assert c.post(f"/api/admin/meldungen/{m['id']}", json={"status": "freigegeben", "eintrag": ent}, headers=ha).json()["ok"]
    assert any(e["t"] == "Testförderung" for e in c.get("/api/programme").json())
    c.post("/api/password/forgot", json={"email": "nutzer@t.de"})
    tok = re.findall(r"\?reset=(\S+)", OUTBOX.read_text())[-1]
    assert "token" in c.post("/api/password/reset", json={"token": tok, "password": "neuespass123"}).json()
    assert c.get("/api/me", headers=hu).status_code == 401
    assert c.post("/api/password/reset", json={"token": tok, "password": "neuespass123"}).status_code == 400
    OUTBOX.unlink()


def test_pvog_parser_tolerant():
    from importer.sources import pvog

    class R:
        def __init__(s, j): s._j = j
        def json(s): return s._j

    class S:
        def get(s, url, params=None, headers=None, respect_robots=True):
            if "locations" in url:
                return R({"items": [{"ars": "064330012012"}]})
            return R({"x": [{"leistung": {"id": "L1", "name": {"de": "Wohngeld beantragen"}}}, {"id": "L2", "leistungsname": "Personalausweis beantragen"}]})
    rows = pvog.fetch({"orte": [{"name": "Riedstadt", "plz": "64560"}], "begriffe": ["Wohngeld"]}, session=S())
    assert [r["t"] for r in rows] == ["Wohngeld beantragen"] and rows[0]["r"] == "HE"


class _R:
    def __init__(s, j): s._j = j
    def json(s): return s._j


def test_spanien_und_oparl_parser(monkeypatch):
    from importer.sources import national, oparl

    class S:
        def __init__(s, *a, **k): s.n = 0
        def get(s, url, params=None, headers=None, respect_robots=True):
            s.n += 1
            if "infosubvenciones" in url:
                return _R({"content": [{"numeroConvocatoria": "123", "descripcion": "Subvenciones a asociaciones juveniles", "nivel1": "LOCAL", "nivel2": "Ayuntamiento de X"}]} if s.n == 1 else {"content": []})
            if url.endswith("/body/1"):
                return _R({"paper": "https://x/paper"})
            return _R({"data": [{"name": "Neufassung der Vereinsförderrichtlinie", "date": date.today().isoformat(), "mainFile": {"accessUrl": "https://x/f.pdf"}},
                                {"name": "Bebauungsplan Nord", "date": date.today().isoformat()}], "links": {}})
    monkeypatch.setattr(national, "PoliteSession", S)
    monkeypatch.setattr(oparl, "PoliteSession", S)
    es = national.fetch_es({"max_pages": 3})
    assert es[0]["c"] == "ES" and "verein" in es[0]["z"] and "123" in es[0]["url"]
    op = oparl.fetch({"quellen": [{"ort": "Teststadt", "body": "https://x/body/1"}]})
    assert len(op) == 1 and op[0]["ort"] == ["Teststadt"] and op[0]["url"] == "https://x/f.pdf"


def test_kommunen_scraper(monkeypatch, tmp_path):
    from importer.sources import kommunen as K
    monkeypatch.setattr(K, "VERZ", tmp_path / "k.json"); monkeypatch.setattr(K, "STATE", tmp_path / "s.json")
    monkeypatch.setattr(K, "ROOT", tmp_path)
    binds = [{"key": {"value": f"0644{i:04d}"}, "name": {"value": f"Ort{i}"}, "web": {"value": f"https://ort{i}.de"}, "typ": {"value": "gemeinde"}} for i in range(600)]
    binds.append({"key": {"value": "06433"}, "name": {"value": "Kreis Groß-Gerau"}, "web": {"value": "https://kreisgg.de"}, "typ": {"value": "kreis"}})
    binds.append({"key": {"value": "06433012"}, "name": {"value": "Riedstadt"}, "web": {"value": "https://riedstadt.de"}, "typ": {"value": "gemeinde"}})
    SEITEN = {
        "https://kreisgg.de": '<a href="/buergerservice/foerderprogramm-dachbegruenung">Förderprogramm Dachbegrünung</a><a href="/kontakt">Kontakt</a>',
        "https://kreisgg.de/buergerservice/foerderprogramm-dachbegruenung": "<main><h1>Förderprogramm Dachbegrünung</h1><p>Der Kreis gewährt einen Zuschuss von bis zu 50 % der förderfähigen Kosten, höchstens 3.000 Euro. Antrag bis zum 31.03.2027 mit Antragsformular.</p></main>",
        "https://riedstadt.de": "<p>Willkommen</p>",
        "https://riedstadt.de/sitemap.xml": "<urlset><url><loc>https://riedstadt.de/leben/vereinsfoerderung</loc></url><url><loc>https://riedstadt.de/rathaus/oeffnungszeiten</loc></url></urlset>",
        "https://riedstadt.de/leben/vereinsfoerderung": "<main><h1>Vereinsförderung</h1><p>Vereine erhalten Zuschüsse nach der Richtlinie; Antrag beim Magistrat. Pauschal 500 Euro je Verein.</p></main>",
    }

    class R:
        def __init__(s, t): s.text = t
        def json(s): return {"results": {"bindings": binds}}

    class S:
        def get(s, url, params=None, headers=None, respect_robots=True, timeout=None):
            if "wikidata" in url: return R("")
            if url.rstrip("/") in SEITEN: return R(SEITEN[url.rstrip("/")])
            raise IOError("404")
        def post(s, *a, **k): raise IOError("kein OSM nötig")
    rows = K.fetch({"pro_lauf": 3}, session=S(), alte=[])
    titel = {r["t"]: r for r in rows}
    assert "Kreis Groß-Gerau: Förderprogramm Dachbegrünung" in titel and "Riedstadt: Vereinsförderung" in titel
    d = titel["Kreis Groß-Gerau: Förderprogramm Dachbegrünung"]
    assert (d["r"], d["q"], d["ea"], d["max"], d["frist"]) == ("HE", 50, 50, 3000, "2027-03-31") and "Riedstadt" in d["ort"]
    st = json.loads((tmp_path / "s.json").read_text()); assert st["pos"] == 3 and st["kommunen_gesamt"] == 602
