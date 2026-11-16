"""Allgemeiner, höflicher Webseiten-Scraper für Kreise, Städte, Länder und Stiftungen ohne Schnittstelle.

Zwei Modi je Website (in importer/sources.yaml oder im Redaktionsbereich eintragbar):
  auto:  start_url + link_muster (Regex für Detailseiten). Detailseiten werden ohne CSS-Wissen gelesen:
         Titel aus h1/og:title, Text aus <main>/<article>/größtem Textblock, Beträge/Quote/Eigenanteil/Frist per Textmuster.
  css:   item / fields / next als CSS-Selektoren, wenn eine Seite sauber strukturiert ist.
Regeln: robots.txt, Pause zwischen Abrufen, eindeutiger User-Agent, Seitenlimit.
"""
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from ..common import PoliteSession, make_entry, slug

FRIST = re.compile(r"(?:Frist|Antragsfrist|Einsendeschluss|Bewerbungsschluss|bis zum)\D{0,20}(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)


def text_of(node, sel):
    if not sel:
        return ""
    n = node.select_one(sel)
    return n.get_text(" ", strip=True) if n else ""


def main_text(soup):
    for sel in ("main", "article", "[role=main]", "#content", ".content"):
        n = soup.select_one(sel)
        if n and len(n.get_text(" ", strip=True)) > 200:
            return n.get_text(" ", strip=True)
    best = max(soup.find_all(["div", "section"]), key=lambda d: len(d.find_all("p", recursive=False)), default=None)
    return best.get_text(" ", strip=True) if best else soup.get_text(" ", strip=True)


def read_detail(html, url, cfg):
    soup = BeautifulSoup(html, "lxml")
    og = soup.find("meta", property="og:title")
    titel = (soup.h1.get_text(" ", strip=True) if soup.h1 else "") or (og["content"] if og else "")
    txt = re.sub(r"\s+", " ", main_text(soup))[:6000]
    e = make_entry(id=cfg["name"] + "-" + slug(titel or url), titel=titel or url, geber=cfg.get("geber", ""), text=txt,
                   gebiet=cfg.get("gebiet", ""), berechtigte=cfg.get("berechtigte", "") + " " + txt[:500], bereich=txt[:800],
                   url=url, quelle="scrape", ebene=cfg.get("ebene"))
    m = FRIST.search(txt)
    if m:
        e["frist"] = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if re.search(r"(kein|ohne)\s+Eigen(anteil|mittel)", txt, re.I):
        e["ea"], e["q"], e["auto"] = 0, 100, True
    if cfg.get("ort"):
        e["ort"] = cfg["ort"] if isinstance(cfg["ort"], list) else [cfg["ort"]]
    return e


def probe(url):
    s = PoliteSession(delay=1)
    soup = BeautifulSoup(s.get(url).text, "lxml")
    print("Titel:", soup.title.get_text(strip=True) if soup.title else "-")
    host = urlparse(url).netloc
    links = sorted({urljoin(url, a["href"]) for a in soup.select("a[href]") if urlparse(urljoin(url, a["href"])).netloc == host})
    print(f"{len(links)} interne Links, z. B.:", *links[:40], sep="\n  ")
    print("Tipp: gemeinsamen Teil der Detail-Links als link_muster eintragen, z. B. '/foerderung/.+'")


def fetch(cfg):
    s = PoliteSession(delay=cfg.get("delay", 3))
    out, url, pages, seen = [], cfg["start_url"], 0, set()
    muster = re.compile(cfg["link_muster"]) if cfg.get("link_muster") else None
    while url and pages < cfg.get("max_pages", 5):
        soup = BeautifulSoup(s.get(url).text, "lxml")
        pages += 1
        if cfg.get("modus", "auto") == "auto":
            for a in soup.select("a[href]"):
                link = urljoin(url, a["href"])
                if link in seen or not muster or not muster.search(link):
                    continue
                seen.add(link)
                try:
                    out.append(read_detail(s.get(link).text, link, cfg))
                except Exception as ex:
                    print("  übersprungen:", link, ex)
                if len(seen) >= cfg.get("max_eintraege", 200):
                    break
        else:
            for item in soup.select(cfg["item"]):
                titel = text_of(item, cfg["fields"]["titel"])
                a = item.select_one(cfg["fields"].get("link", "a"))
                link = urljoin(url, a["href"]) if a and a.get("href") else url
                out.append(make_entry(id=cfg["name"] + "-" + slug(titel), titel=titel, geber=cfg.get("geber", ""),
                                      text=text_of(item, cfg["fields"].get("text")), gebiet=cfg.get("gebiet", ""),
                                      berechtigte=cfg.get("berechtigte", ""), url=link, quelle="scrape", ebene=cfg.get("ebene")))
        nxt = soup.select_one(cfg["next"]) if cfg.get("next") else None
        url = urljoin(url, nxt["href"]) if nxt and nxt.get("href") else None
    return out
