# Fördernavi

Kostenlose Plattform: Förderungen von EU, Bund, Ländern, Kreisen, Städten, Stiftungen und Lotterien finden,
Anträge vorbereiten und verwalten. Läuft ohne KI; Claude oder ChatGPT sind optional.

## Stand (29.09.2026)

| Teil | Status |
|---|---|
| Startdaten, 36 Einträge | 29 gegen Quellen geprüft (Belege im Eintrag), 4 teilweise geprüft, 3 Platzhalter |
| Website: Assistent, Eigenanteil-Filter, Quellenfilter, Ortsfilter, Merkliste, Anträge, Texte, KI optional | getestet (Chromium, mobil) |
| Konten, Sync, Passwort zurücksetzen per E-Mail, Konto löschen | getestet |
| Redaktion: Quellen ein/aus (auch DSEE), Import starten, Websites anlegen, Meldungen prüfen/freigeben, Einträge korrigieren, Rollen | getestet |
| Förderdatenbank-Import (offizieller ZIP/XML-Export) | mit echten Exportdateien getestet |
| EU-Import (Search API) | Abfrage nach dokumentierter Referenz korrigiert; **live noch nicht getestet** |
| DSEE-Import | Struktur am 29.09.2026 geprüft; Parser nur mit nachgebautem HTML getestet; **standardmäßig aus** |
| Allgemeiner Website-Scraper (Kreise, Städte) | Gerüst, je Website einrichten |
| Barrierefreiheit | axe-core, WCAG 2.1 AA: 0 automatisch erkennbare Verstöße (hell/dunkel). Ersetzt keinen Test mit Screenreader-Nutzern |
| GitHub-Variante (Handy, ohne Server) | siehe ANLEITUNG-GITHUB.md; getestet mit 2.600 Einträgen: 2,7 MB, offline nutzbar |
| Last | 1 CPU, 2 Worker: ~180 Anfragen/s Programmliste, 0 Fehler bei 50 gleichzeitigen Nutzern |

## Installation

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m importer.run --probe fdb      # Förderdatenbank testen
python -m importer.run --probe eu       # EU-API testen
python -m importer.run                  # Import -> data/programme.json
python build.py                         # Website bauen
python -m pytest -q tests               # Tests
uvicorn server.app:app --host 127.0.0.1 --port 8000
```
Produktion: `fordernavi.service.beispiel` (systemd) und `Caddyfile.beispiel` (HTTPS). Import täglich per Cron:
`30 4 * * * cd /srv/fordernavi && .venv/bin/python -m importer.run`

Das **erste registrierte Konto** wird Redaktion, außer `FN_ADMIN_EMAILS` ist gesetzt. Ohne SMTP-Einstellungen
landen Reset-Links in `data/mail_outbox.log` – nur für Tests, in Produktion SMTP eintragen.

## Kommunale Ebene

1. **Meldungen**: Jede Person kann Förderungen melden (strukturiert mit Quote, Eigenanteil, Frist, Link). Die Redaktion prüft
   an der Quelle und gibt frei; der Link wird als Beleg gespeichert.
2. **Partnerkommunen**: Die Redaktion vergibt die Rolle „Kommune“ mit Ort. Deren Meldungen sind markiert.
3. **Websites**: Im Redaktionsbereich Startseite + Linkmuster eintragen (Hilfe: `python -m importer.run --probe-url URL`),
   nach Probelauf einschalten.
Einträge mit Ort erscheinen nur, wenn die Nutzerin diesen Ort eingibt (oder keinen Ort angibt).

## Recht und Datenschutz (Einschätzung, keine Rechtsberatung)

- Impressum (§ 5 DDG) und Datenschutzerklärung ausfüllen; Auftragsverarbeitungsvertrag mit Hoster und Mailanbieter.
- **Schriften**: Der eigene Server bindet keine Google Fonts ein (Urteil LG München I, 2022). Eigene Schriftdateien
  (z. B. Atkinson Hyperlegible, Open Font License) nach `web/fonts/` legen und `fonts.css` mit `@font-face` anlegen.
- **Förderdatenbank**: FAQ nennt CC BY 4.0 für den Export, das Impressum CC BY-ND 4.0 für Website-Texte. Originaltexte bleiben
  deshalb unverändert; Namensnennung erfolgt. Vor dem Start schriftlich klären.
- **DSEE**: Datenbankschutz §§ 87a ff. UrhG – vor dem Einschalten Freigabe einholen.
- **Scraping**: robots.txt wird beachtet; `USER_AGENT` in `importer/common.py` mit echter Kontaktadresse versehen.
- **KI**: Schlüssel bleiben im Browser; in der Datenschutzerklärung auf die Datenweitergabe an den gewählten Anbieter hinweisen.
- **Spenden**: Quittungen nur bei anerkannter Gemeinnützigkeit.

## Herkunft übernommener Erkenntnisse
- Aufbau des FDB-Exports und Testdateien: https://github.com/CorrelAid/fdb_scraper (MIT)
- Abfragedetails der EU-Search-API: https://github.com/pipeworx-io/mcp-eu-funding-tenders (MIT)

## Offen
- EU- und DSEE-Import live auf dem Server testen; DSEE-Freigabe anfragen.
- Test mit echten Nutzern (inkl. Screenreader), Datenschutzerklärung, Impressum.
- Doppelte Einträge zwischen Grunddaten und Förderdatenbank (z. B. „Einstiegsgeld“) werden nur bei gleichem Titel zusammengeführt;
  sonst in der Redaktion einen der beiden ausblenden.
