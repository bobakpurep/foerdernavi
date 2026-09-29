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


PWA_HEAD = """<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#16324F">
<link rel="icon" href="icon-192.png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Fördernavi">
<script>if("serviceWorker" in navigator){addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}));}</script>"""

SW = """// Offline-Fähigkeit: erst Netz (aktuelle Daten), bei Funkloch die zuletzt geladene Version.
const C="fordernavi-v1";
self.addEventListener("install",e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(["./","./index.html","./manifest.webmanifest","./icon-192.png"])));self.skipWaiting();});
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", action="store_true")
    ap.add_argument("--kontakt", default="", help="E-Mail für Meldungen (ohne Server)")
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
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "sw.js").write_text(SW, encoding="utf-8")
    (out / "manifest.webmanifest").write_text(json.dumps({
        "name": "Fördernavi – Förderungen finden", "short_name": "Fördernavi", "lang": "de", "start_url": "./",
        "scope": "./", "display": "standalone", "background_color": "#F6F8FA", "theme_color": "#16324F",
        "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    icons(out)
    print(f"_site/ gebaut: {len(data)} Einträge, index.html {len(html.encode()) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
