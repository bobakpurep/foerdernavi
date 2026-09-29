"""Fördernavi-Server: Website, Programmdaten, kostenlose Nutzerkonten, Redaktionsbereich.

Umgebungsvariablen:
  FN_DB            Pfad der SQLite-Datenbank (Standard data/fordernavi.sqlite3)
  FN_ADMIN_EMAILS  Komma-Liste der E-Mails mit Redaktionsrechten (sonst wird das erste Konto Redaktion)
  FN_BASE_URL      öffentliche Adresse, z. B. https://foerdernavi.de (für Links in E-Mails)
  FN_SMTP_HOST, FN_SMTP_PORT (587), FN_SMTP_USER, FN_SMTP_PASS, FN_SMTP_FROM
                   Ohne SMTP werden Reset-Links in data/mail_outbox.log geschrieben (nur für Tests!).
Start: uvicorn server.app:app --host 127.0.0.1 --port 8000
"""
import hashlib, hmac, json, os, re, secrets, smtplib, sqlite3, threading, time
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("FN_DB", ROOT / "data" / "fordernavi.sqlite3"))
PROGRAMME = ROOT / "data" / "programme.json"
SEED = ROOT / "data" / "programme.seed.json"
OUTBOX = ROOT / "data" / "mail_outbox.log"
SESSION_DAYS, RESET_MIN, MAX_STATE = 30, 60, 512_000
EDIT_FIELDS = {"t", "g", "e", "r", "ort", "z", "th", "a", "rz", "q", "ea", "max", "frist", "url", "hin", "kirche", "quelle", "pruef", "versteckt"}

app = FastAPI(title="Fördernavi", docs_url=None, redoc_url=None)
_import_lock = threading.Lock()
_import_state = {"laeuft": False}


def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash BLOB NOT NULL,
            salt BLOB NOT NULL, created REAL NOT NULL, rolle TEXT NOT NULL DEFAULT 'nutzer', ort TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS resets(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS state(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, json TEXT NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS meldungen(id INTEGER PRIMARY KEY, json TEXT NOT NULL, created REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'offen', von_user INTEGER, notiz TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS korrekturen(prog_id TEXT PRIMARY KEY, json TEXT NOT NULL, updated REAL NOT NULL, von_user INTEGER);
        CREATE TABLE IF NOT EXISTS ratelimit(key TEXT PRIMARY KEY, count INTEGER, window REAL);
        """)


init_db()


# ---------- Hilfen ----------
def hash_pw(pw, salt):
    return hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def th(t):
    return hashlib.sha256(t.encode()).hexdigest()


def ip(request):
    return request.client.host if request.client else "?"


def rate_limit(key, limit, per):
    """Atomar (ein SQL-Befehl), damit parallele Anfragen und mehrere Worker die Grenze nicht umgehen."""
    now = time.time()
    with db() as con:
        cnt = con.execute("""INSERT INTO ratelimit(key,count,window) VALUES(?,1,?)
            ON CONFLICT(key) DO UPDATE SET
              count = CASE WHEN ? - window > ? THEN 1 ELSE count + 1 END,
              window = CASE WHEN ? - window > ? THEN ? ELSE window END
            RETURNING count""", (key, now, now, per, now, per, now)).fetchone()[0]
    if cnt > limit:
        raise HTTPException(429, "Zu viele Versuche. Bitte später erneut.")


def user_from(auth):
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Nicht angemeldet.")
    with db() as con:
        row = con.execute("SELECT u.* , s.expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
                          (th(auth[7:]),)).fetchone()
    if not row or row["expires"] < time.time():
        raise HTTPException(401, "Sitzung abgelaufen. Bitte neu anmelden.")
    return row


def admin_from(auth):
    u = user_from(auth)
    if u["rolle"] != "redaktion":
        raise HTTPException(403, "Nur für die Redaktion.")
    return u


def new_session(uid):
    t = secrets.token_urlsafe(32)
    with db() as con:
        con.execute("INSERT INTO sessions VALUES(?,?,?)", (th(t), uid, time.time() + SESSION_DAYS * 86400))
    return t


def admin_emails():
    return {e.strip().lower() for e in os.environ.get("FN_ADMIN_EMAILS", "").split(",") if e.strip()}


def send_mail(to, subject, body):
    host = os.environ.get("FN_SMTP_HOST")
    if not host:
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M')} an {to}: {subject}\n{body}\n")
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.environ.get("FN_SMTP_FROM", os.environ.get("FN_SMTP_USER", "")), to, subject
    msg.set_content(body)
    with smtplib.SMTP(host, int(os.environ.get("FN_SMTP_PORT", "587")), timeout=20) as s:
        s.starttls()
        if os.environ.get("FN_SMTP_USER"):
            s.login(os.environ["FN_SMTP_USER"], os.environ.get("FN_SMTP_PASS", ""))
        s.send_message(msg)


def programmes():
    """Startdaten/Import + freigegebene Meldungen + Korrekturen der Redaktion."""
    src = PROGRAMME if PROGRAMME.exists() else SEED
    data = {e["id"]: e for e in json.loads(src.read_text(encoding="utf-8"))}
    with db() as con:
        for r in con.execute("SELECT id, json FROM meldungen WHERE status='freigegeben'"):
            m = json.loads(r["json"])
            if m.get("eintrag"):
                data[m["eintrag"]["id"]] = m["eintrag"]
        for r in con.execute("SELECT prog_id, json FROM korrekturen"):
            if r["prog_id"] in data:
                data[r["prog_id"]].update(json.loads(r["json"]))
    return [e for e in data.values() if not e.get("versteckt")]


# ---------- Modelle ----------
class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=10, max_length=200)


class ResetStart(BaseModel):
    email: str = Field(min_length=5, max_length=200)


class ResetDone(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=10, max_length=200)


class Meldung(BaseModel):
    titel: str = Field(min_length=2, max_length=300)
    geber: str = Field(default="", max_length=300)
    ebene: str = Field(default="Kreis/Stadt", max_length=30)
    land: str = Field(default="", max_length=2)
    ort: str = Field(default="", max_length=200)
    zielgruppen: list[str] = Field(default_factory=list, max_length=10)
    art: str = Field(default="zuschuss", max_length=20)
    quote: float | None = Field(default=None, ge=0, le=100)
    eigenanteil: float | None = Field(default=None, ge=0, le=100)
    max: float | None = Field(default=None, ge=0, le=1e9)
    frist: str = Field(default="", max_length=100)
    url: str = Field(default="", max_length=500)
    text: str = Field(default="", max_length=4000)


# ---------- Konto ----------
@app.post("/api/register")
def register(c: Credentials, request: Request):
    rate_limit("reg:" + ip(request), 5, 3600)
    email = c.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Bitte eine gültige E-Mail-Adresse angeben.")
    salt = secrets.token_bytes(16)
    with db() as con:
        erste = con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        rolle = "redaktion" if (email in admin_emails() or (erste and not admin_emails())) else "nutzer"
        try:
            uid = con.execute("INSERT INTO users(email,pw_hash,salt,created,rolle) VALUES(?,?,?,?,?)",
                              (email, hash_pw(c.password, salt), salt, time.time(), rolle)).lastrowid
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Für diese E-Mail gibt es bereits ein Konto.")
    return {"token": new_session(uid)}


@app.post("/api/login")
def login(c: Credentials, request: Request):
    rate_limit("login:" + ip(request), 10, 900)
    with db() as con:
        row = con.execute("SELECT id, pw_hash, salt FROM users WHERE email=?", (c.email.strip().lower(),)).fetchone()
    if not row or not hmac.compare_digest(row["pw_hash"], hash_pw(c.password, row["salt"])):
        raise HTTPException(401, "E-Mail oder Passwort falsch.")
    return {"token": new_session(row["id"])}


@app.get("/api/me")
def me(authorization: str | None = Header(default=None)):
    u = user_from(authorization)
    return {"email": u["email"], "rolle": u["rolle"], "ort": u["ort"]}


@app.post("/api/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        with db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (th(authorization[7:]),))
    return {"ok": True}


@app.delete("/api/account")
def delete_account(authorization: str | None = Header(default=None)):
    u = user_from(authorization)
    with db() as con:
        con.execute("DELETE FROM users WHERE id=?", (u["id"],))
    return {"ok": True}


@app.post("/api/password/forgot")
def forgot(r: ResetStart, request: Request):
    rate_limit("forgot:" + ip(request), 5, 3600)
    email = r.email.strip().lower()
    with db() as con:
        row = con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row:
            t = secrets.token_urlsafe(32)
            con.execute("INSERT INTO resets VALUES(?,?,?)", (th(t), row["id"], time.time() + RESET_MIN * 60))
            base = os.environ.get("FN_BASE_URL", str(request.base_url).rstrip("/"))
            send_mail(email, "Fördernavi: Passwort zurücksetzen",
                      f"Guten Tag,\n\nüber diesen Link können Sie ein neues Passwort festlegen (gültig {RESET_MIN} Minuten):\n"
                      f"{base}/?reset={t}\n\nWenn Sie das nicht angefordert haben, ignorieren Sie diese E-Mail.\n")
    # immer gleiche Antwort: verrät nicht, ob ein Konto existiert
    return {"ok": True, "hinweis": "Falls ein Konto existiert, wurde eine E-Mail verschickt."}


@app.post("/api/password/reset")
def reset(r: ResetDone):
    with db() as con:
        row = con.execute("SELECT user_id, expires FROM resets WHERE token_hash=?", (th(r.token),)).fetchone()
        if not row or row["expires"] < time.time():
            raise HTTPException(400, "Der Link ist ungültig oder abgelaufen. Bitte neu anfordern.")
        salt = secrets.token_bytes(16)
        con.execute("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (hash_pw(r.password, salt), salt, row["user_id"]))
        con.execute("DELETE FROM resets WHERE user_id=?", (row["user_id"],))
        con.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
    return {"token": new_session(row["user_id"])}


@app.get("/api/state")
def get_state(authorization: str | None = Header(default=None)):
    u = user_from(authorization)
    with db() as con:
        row = con.execute("SELECT json FROM state WHERE user_id=?", (u["id"],)).fetchone()
    return json.loads(row["json"]) if row else {"merk": [], "apps": []}


@app.put("/api/state")
async def put_state(request: Request, authorization: str | None = Header(default=None)):
    u = user_from(authorization)
    body = await request.body()
    if len(body) > MAX_STATE:
        raise HTTPException(413, "Zu viele Daten.")
    d = json.loads(body)
    clean = {"merk": list(d.get("merk", []))[:1000], "apps": list(d.get("apps", []))[:500]}
    with db() as con:
        con.execute("REPLACE INTO state VALUES(?,?,?)", (u["id"], json.dumps(clean, ensure_ascii=False), time.time()))
    return {"ok": True}


# ---------- Öffentliche Daten ----------
@app.get("/api/programme")
def api_programme():
    return JSONResponse(programmes(), headers={"Cache-Control": "no-cache"})


@app.post("/api/meldungen")
def meldung(m: Meldung, request: Request, authorization: str | None = Header(default=None)):
    rate_limit("meld:" + ip(request), 20, 3600)
    uid, d = None, m.model_dump()
    try:
        if authorization:
            u = user_from(authorization)
            uid = u["id"]
            if u["rolle"] == "kommune":
                d["partnerkommune"] = u["ort"]   # Meldung einer verifizierten Kommune: vorrangig prüfen
    except HTTPException:
        pass
    with db() as con:
        con.execute("INSERT INTO meldungen(json,created,von_user) VALUES(?,?,?)", (json.dumps(d, ensure_ascii=False), time.time(), uid))
    return {"ok": True}


# ---------- Redaktion ----------
def _sources():
    from importer.run import load_cfg
    return load_cfg()


@app.get("/api/admin/uebersicht")
def admin_overview(authorization: str | None = Header(default=None)):
    admin_from(authorization)
    cfg = _sources()
    quellen = [{"key": k, "name": n, "enabled": bool(cfg.get(k, {}).get("enabled"))}
               for k, n in (("fdb", "Förderdatenbank des Bundes"), ("eu_sedia", "EU Funding & Tenders"), ("dsee", "DSEE-Förderdatenbank"))]
    quellen += [{"key": s["name"], "name": s["name"], "enabled": bool(s.get("enabled")), "website": s.get("start_url")} for s in cfg.get("scrape") or []]
    log = ROOT / "data" / "import.log.json"
    with db() as con:
        offen = con.execute("SELECT COUNT(*) FROM meldungen WHERE status='offen'").fetchone()[0]
        nutzer = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"quellen": quellen, "import": json.loads(log.read_text(encoding="utf-8")) if log.exists() else None,
            "import_laeuft": _import_state["laeuft"], "meldungen_offen": offen, "nutzer": nutzer, "eintraege": len(programmes())}


class Toggle(BaseModel):
    key: str
    enabled: bool


@app.post("/api/admin/quelle")
def admin_toggle(t: Toggle, authorization: str | None = Header(default=None)):
    admin_from(authorization)
    from importer.run import load_cfg, save_cfg
    cfg = load_cfg()
    if t.key in ("fdb", "eu_sedia", "dsee"):
        cfg.setdefault(t.key, {})["enabled"] = t.enabled
    else:
        for s in cfg.get("scrape") or []:
            if s["name"] == t.key:
                s["enabled"] = t.enabled
                break
        else:
            raise HTTPException(404, "Quelle unbekannt.")
    save_cfg(cfg)
    return {"ok": True}


class Website(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    start_url: str = Field(pattern=r"^https?://", max_length=500)
    link_muster: str = Field(min_length=2, max_length=200)
    ebene: str = "Kreis/Stadt"
    gebiet: str = ""
    ort: str = ""
    geber: str = ""
    berechtigte: str = "verein"


@app.post("/api/admin/website")
def admin_add_site(w: Website, authorization: str | None = Header(default=None)):
    admin_from(authorization)
    from importer.run import load_cfg, save_cfg
    cfg = load_cfg()
    cfg["scrape"] = [s for s in (cfg.get("scrape") or []) if s["name"] != w.name] + [dict(w.model_dump(), modus="auto", enabled=False, max_pages=3, delay=3)]
    save_cfg(cfg)
    return {"ok": True, "hinweis": "Website angelegt (ausgeschaltet). Nach Prüfung einschalten."}


def _run_import():
    try:
        from importer.run import run
        run()
    finally:
        _import_state["laeuft"] = False


@app.post("/api/admin/import")
def admin_import(authorization: str | None = Header(default=None)):
    admin_from(authorization)
    with _import_lock:
        if _import_state["laeuft"]:
            raise HTTPException(409, "Import läuft bereits.")
        _import_state["laeuft"] = True
    threading.Thread(target=_run_import, daemon=True).start()
    return {"ok": True}


@app.get("/api/admin/meldungen")
def admin_meldungen(authorization: str | None = Header(default=None)):
    admin_from(authorization)
    with db() as con:
        rows = con.execute("SELECT id, json, created, status, notiz FROM meldungen ORDER BY status='offen' DESC, created DESC LIMIT 300").fetchall()
    return [{"id": r["id"], "status": r["status"], "notiz": r["notiz"], "created": r["created"], **json.loads(r["json"])} for r in rows]


class Entscheidung(BaseModel):
    status: str = Field(pattern="^(freigegeben|abgelehnt)$")
    notiz: str = Field(default="", max_length=1000)
    eintrag: dict | None = None     # von der Redaktion geprüfter Eintrag im Programmschema


@app.post("/api/admin/meldungen/{mid}")
def admin_decide(mid: int, e: Entscheidung, authorization: str | None = Header(default=None)):
    u = admin_from(authorization)
    with db() as con:
        row = con.execute("SELECT json FROM meldungen WHERE id=?", (mid,)).fetchone()
        if not row:
            raise HTTPException(404, "Meldung nicht gefunden.")
        m = json.loads(row["json"])
        if e.status == "freigegeben":
            if not e.eintrag or not e.eintrag.get("t"):
                raise HTTPException(400, "Für die Freigabe wird ein vollständiger Eintrag benötigt.")
            ent = {k: v for k, v in e.eintrag.items() if k in EDIT_FIELDS}
            ent.update(id=f"meldung-{mid}", quelle=ent.get("quelle") or "geprueft",
                       pruef={"datum": date.today().isoformat(), "belege": [m.get("url")] if m.get("url") else [], "durch": "Redaktion"})
            ent.setdefault("z", ["verein"]); ent.setdefault("th", []); ent.setdefault("a", "zuschuss"); ent.setdefault("rz", "nein")
            ent.setdefault("e", "Kreis/Stadt"); ent.setdefault("r", "lokal")
            m["eintrag"] = ent
        con.execute("UPDATE meldungen SET status=?, notiz=?, json=? WHERE id=?", (e.status, e.notiz, json.dumps(m, ensure_ascii=False), mid))
    return {"ok": True}


class Korrektur(BaseModel):
    felder: dict


@app.put("/api/admin/eintrag/{pid}")
def admin_correct(pid: str, k: Korrektur, authorization: str | None = Header(default=None)):
    u = admin_from(authorization)
    f = {a: b for a, b in k.felder.items() if a in EDIT_FIELDS}
    if f.get("quelle") == "geprueft" and not f.get("pruef"):
        f["pruef"] = {"datum": date.today().isoformat(), "belege": [], "durch": "Redaktion"}
    with db() as con:
        old = con.execute("SELECT json FROM korrekturen WHERE prog_id=?", (pid,)).fetchone()
        merged = {**(json.loads(old["json"]) if old else {}), **f}
        con.execute("REPLACE INTO korrekturen VALUES(?,?,?,?)", (pid, json.dumps(merged, ensure_ascii=False), time.time(), u["id"]))
    return {"ok": True}


class Rolle(BaseModel):
    email: str
    rolle: str = Field(pattern="^(nutzer|redaktion|kommune)$")
    ort: str = ""


@app.post("/api/admin/rolle")
def admin_role(r: Rolle, authorization: str | None = Header(default=None)):
    admin_from(authorization)
    with db() as con:
        n = con.execute("UPDATE users SET rolle=?, ort=? WHERE email=?", (r.rolle, r.ort, r.email.strip().lower())).rowcount
    if not n:
        raise HTTPException(404, "Konto nicht gefunden.")
    return {"ok": True}


# ---------- Website ----------
@app.get("/")
def index():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    html = html.replace('<meta name="api-base" content="">', '<meta name="api-base" content="/api">')
    # Datenschutz: keine Google-Fonts-Einbindung auf dem eigenen Server. Eigene Schriftdateien unter web/fonts/ ablegen
    # (fonts.css mit @font-face), dann werden sie statt Google Fonts geladen; sonst Systemschriften.
    html = re.sub(r'<link rel="preconnect"[^>]*>\s*', '', html)
    local = (ROOT / "web" / "fonts" / "fonts.css").exists()
    html = re.sub(r'<link href="https://fonts.googleapis.com[^>]*>', '<link href="/fonts/fonts.css" rel="stylesheet">' if local else '', html)
    return HTMLResponse(html,
                        headers={"Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self' https://api.anthropic.com https://api.openai.com; img-src 'self' data:; frame-ancestors 'none'",
                                 "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin"})


@app.get("/fonts/{name}")
def fonts(name: str):
    from fastapi.responses import FileResponse
    f = (ROOT / "web" / "fonts" / name).resolve()
    if f.parent != (ROOT / "web" / "fonts").resolve() or not f.exists():
        raise HTTPException(404)
    return FileResponse(f)
