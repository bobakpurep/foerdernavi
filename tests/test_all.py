"""Tests: python -m pytest -q   (aus dem Projektordner)"""
import os, re, sys, json, tempfile, shutil
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
