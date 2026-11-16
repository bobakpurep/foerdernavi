"""Baut die Website.

  python build.py                       -> web/index.html (für Server und Vorschau, vollständige Daten)
  python build.py --site [--kontakt X]  -> _site/ für GitHub Pages: kompakte Daten, installierbar (PWA), offline nutzbar
"""
import argparse, json, pathlib, shutil
root = pathlib.Path(__file__).parent


def load_data():
    src = root / "data" / "programme.json"
    if not src.exists():
        src = root / "data" / "programme.seed.json"
    return json.loads(src.read_text(encoding="utf-8")), src.name


def compact(data):
    """Lange Originaltexte weglassen (Detail steht auf der verlinkten Seite), Hinweise kürzen."""
    out = []
    for e in data:
        e = {k: v for k, v in e.items() if k not in ("text", "stand") and (k in ("z", "th") or v not in (None, "", []))}
        if len(e.get("hin", "")) > 380:
            e["hin"] = e["hin"][:377].rsplit(" ", 1)[0] + " …"
        out.append(e)
    return out


def render(data, meta, pwa=""):
    tpl = (root / "web" / "index.template.html").read_text(encoding="utf-8")
    js = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return tpl.replace("/*SEED_DATA*/[]", js(data)).replace("/*META*/{}", js(meta)).replace("<!--PWA-->", pwa)


PWA_HEAD = """<link rel="alternate" hreflang="de" href="./"><link rel="alternate" hreflang="en" href="en/">
<link rel="alternate" type="application/atom+xml" title="Neue Förderungen" href="feed.xml">
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#16324F">
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Fördernavi">
<script>if("serviceWorker" in navigator){addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}));}</script>"""

SW = """// Offline-Fähigkeit: erst Netz (aktuelle Daten), bei Funkloch die zuletzt geladene Version.
const C="fordernavi-v2";
self.addEventListener("install",e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(["./","./index.html","./manifest.webmanifest","./icon-192.png","./fonts/fonts.css"])));self.skipWaiting();});
self.addEventListener("activate",e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x))))));
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",e=>{const u=new URL(e.request.url);if(e.request.method!=="GET"||u.origin!==location.origin)return;
  e.respondWith(fetch(e.request).then(r=>{const k=r.clone();caches.open(C).then(c=>c.put(e.request,k));return r;}).catch(()=>caches.match(e.request).then(r=>r||caches.match("./index.html"))));});
"""


def icons(out):
    try:
        from PIL import Image, ImageDraw
    except ImportError:   # ohne Pillow: Seite trotzdem bauen, nur ohne App-Symbole
        print("Hinweis: Pillow fehlt, App-Symbole werden übersprungen (pip install Pillow)")
        return
    for size, name in ((192, "icon-192.png"), (512, "icon-512.png"), (180, "apple-touch-icon.png")):
        s = size / 100
        im = Image.new("RGB", (size, size), "#16324F")
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([18 * s, 58 * s, 60 * s, 76 * s], radius=3 * s, fill="#2F9A6C")   # Förderung
        d.rounded_rectangle([60 * s, 58 * s, 82 * s, 76 * s], radius=3 * s, fill="#E0A43A")   # Eigenanteil
        d.line([22 * s, 38 * s, 74 * s, 38 * s], fill="white", width=int(7 * s))
        d.line([60 * s, 24 * s, 76 * s, 38 * s, 60 * s, 52 * s], fill="white", width=int(7 * s), joint="curve")
        im.save(out / name)


THEMEN_SEO = {"familie": "Familie & Kinder", "wohnen": "Wohnen & Eigentum", "bauen": "Bauen & Sanieren", "energie": "Energie & Heizung",
              "gesundheit": "Gesundheit & Pflege", "steuern": "Steuern sparen", "finanzierung": "Finanzierung, Kredite, Bürgschaften",
              "gruendung": "Gründung", "forschung": "Forschung & Innovation", "bildung": "Bildung & Weiterbildung", "jugend": "Jugendarbeit",
              "soziales": "Soziales", "ehrenamt": "Ehrenamt", "kultur": "Kultur & Heimat", "sport": "Sport", "umwelt": "Umwelt & Natur",
              "international": "International", "demokratie": "Demokratie", "denkmal": "Denkmal", "digital": "Digitalisierung"}


def esc(t):
    return (str(t or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def ics_text(t):
    return str(t).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", " ")[:200]


def extras(out, data, html, base):
    """Kostenlose Abo- und Such-Funktionen ohne Server: Kalender, Newsfeed, englische Adresse, Themenseiten, Sitemap."""
    import datetime as dt, re
    heute = dt.date.today().isoformat()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # 1) Kalender-Abo: alle Fristen mit Datum ab heute
    ev = []
    for e in data:
        f = e.get("frist") or ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f) and f >= heute:
            ev += ["BEGIN:VEVENT", f"UID:{e['id']}@fordernavi", f"DTSTAMP:{stamp}", "DTSTART;VALUE=DATE:" + f.replace("-", ""),
                   "SUMMARY:Förderfrist: " + ics_text(e["t"]), "DESCRIPTION:" + ics_text((e.get("g") or "") + " – " + (e.get("url") or "")),
                   "BEGIN:VALARM", "TRIGGER:-P14D", "ACTION:DISPLAY", "DESCRIPTION:Förderfrist in 14 Tagen", "END:VALARM", "END:VEVENT"]
    (out / "fristen.ics").write_text("\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Foerdernavi//DE", "X-WR-CALNAME:Förderfristen (Fördernavi)",
                                                 "X-PUBLISHED-TTL:PT12H", *ev, "END:VCALENDAR"]) + "\r\n", encoding="utf-8")
    # 2) Newsfeed (Atom): die 100 zuletzt aufgenommenen Förderungen
    for e in data:
        e.setdefault("seit", e.get("stand") or (e.get("pruef") or {}).get("datum") or heute)
    neu = sorted(data, key=lambda e: e["seit"], reverse=True)[:100]
    items = "".join(f"<entry><title>{esc(e['t'])}</title><id>urn:fordernavi:{esc(e['id'])}</id><updated>{e['seit']}T00:00:00Z</updated>"
                    f"<link href=\"{esc(e.get('url') or base + '/')}\"/><summary>{esc((e.get('g') or '') + ': ' + (e.get('hin') or '')[:300])}</summary></entry>" for e in neu)
    (out / "feed.xml").write_text(f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Fördernavi – neue Förderungen</title>'
                                  f'<id>{esc(base or "urn:fordernavi")}/feed.xml</id><updated>{heute}T00:00:00Z</updated><link href="{esc(base)}/"/>{items}</feed>', encoding="utf-8")
    # 3) Englische Fassung unter /en/ (gleiche App, startet auf Englisch)
    en = html.replace('<html lang="de">', '<html lang="en">').replace("<!--PWA-->", "").replace("<head>", '<head>\n<base href="../">\n<meta name="start-lang" content="en">', 1)
    en = re.sub(r"<title>.*?</title>", "<title>FundNavi – free funding finder for Germany and the EU (grants, subsidies, loans)</title>", en, count=1)
    en = en.replace('<meta name="description" content="', '<meta name="description" content="Free funding finder for Germany and the EU: grants, subsidies, loans, tax benefits for private persons, families, associations, churches, NGOs and companies. ', 1)
    (out / "en").mkdir(exist_ok=True)
    (out / "en" / "index.html").write_text(en, encoding="utf-8")
    # 4) Themenseiten für Suchmaschinen (statisch, ohne JavaScript lesbar)
    (out / "themen").mkdir(exist_ok=True)
    urls = [base + "/", base + "/en/"]
    links = []
    for key, name in THEMEN_SEO.items():
        sub = [e for e in data if key in (e.get("th") or [])]
        sub.sort(key=lambda e: (e.get("quelle") not in ("geprueft", "teilgeprueft"), e["t"]))
        rows = "".join(f"<li><a href=\"{esc(e.get('url') or '../')}\">{esc(e['t'])}</a> – {esc(e.get('g'))}</li>" for e in sub[:300])
        (out / "themen" / f"{key}.html").write_text(
            f'<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Förderungen: {esc(name)} – Fördernavi</title><meta name="description" content="{len(sub)} Förderprogramme zum Thema {esc(name)}: Zuschüsse, Kredite und Steuervorteile von EU, Bund, Ländern, Kommunen und Stiftungen.">'
            f'<link rel="stylesheet" href="../fonts/fonts.css"><style>body{{font:17px/1.55 "Atkinson Hyperlegible",system-ui,sans-serif;max-width:900px;margin:0 auto;padding:16px;color:#16324F}}a{{color:#1454B8}}</style></head>'
            f'<body><p><a href="../#thema={key}">← Zu Fördernavi mit Filter „{esc(name)}“</a></p><h1>Förderungen: {esc(name)}</h1><p>{len(sub)} Programme (Stand {heute}). '
            f'Alle Angaben ohne Gewähr – maßgeblich ist die Förderrichtlinie.</p><ul>{rows}</ul></body></html>', encoding="utf-8")
        urls.append(f"{base}/themen/{key}.html")
        links.append(f'<a href="themen/{key}.html">{esc(name)}</a>')
    # 5) Sitemap und robots.txt (nur mit bekannter Adresse)
    if base:
        (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                         + "".join(f"<url><loc>{esc(u)}</loc><lastmod>{heute}</lastmod></url>" for u in urls) + "</urlset>", encoding="utf-8")
        (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    # Themenlinks in die Startseite (für Suchmaschinen und als Übersicht)
    idx = (out / "index.html").read_text(encoding="utf-8").replace("<!--THEMENLINKS-->", " · ".join(links))
    (out / "index.html").write_text(idx, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", action="store_true")
    ap.add_argument("--kontakt", default="", help="E-Mail für Meldungen (ohne Server)")
    ap.add_argument("--base-url", default="", help="öffentliche Adresse der Seite (für Sitemap und Feeds)")
    a = ap.parse_args()
    data, src = load_data()
    log = root / "data" / "import.log.json"
    meta = {"import": json.loads(log.read_text(encoding="utf-8")) if log.exists() else None}
    if not a.site:
        (root / "web" / "index.html").write_text(render(data, meta), encoding="utf-8")
        print(f"web/index.html gebaut mit {len(data)} Einträgen aus {src}")
        return
    out = root / "_site"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    meta["kontakt"] = a.kontakt
    html = render(compact(data), meta, PWA_HEAD)
    # Datenschutz: keine Google Fonts auf der öffentlichen Seite – selbst gehostete Schriften aus web/fonts
    import re as _re
    html = _re.sub(r'<link rel="preconnect"[^>]*>\s*', "", html)
    html = _re.sub(r'<link href="https://fonts.googleapis.com[^>]*>', '<link href="fonts/fonts.css" rel="stylesheet">', html)
    shutil.copytree(root / "web" / "fonts", out / "fonts")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "sw.js").write_text(SW, encoding="utf-8")
    (out / "manifest.webmanifest").write_text(json.dumps({
        "name": "Fördernavi – Förderungen finden", "short_name": "Fördernavi", "lang": "de", "start_url": "./",
        "scope": "./", "display": "standalone", "background_color": "#F6F8FA", "theme_color": "#16324F",
        "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    extras(out, data, html, a.base_url.rstrip("/"))
    icons(out)
    print(f"_site/ gebaut: {len(data)} Einträge, index.html {len(html.encode()) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
