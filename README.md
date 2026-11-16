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
| Verwaltungsleistungen (PVOG: Bund, Land, Kommune, z. B. Kindergeld, Wohngeld, Vereinsförderung) | `importer/sources/pvog.py`; öffentliche API geprüft, Antwortformat **nicht** geprüft – erster Lauf zeigt es |
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

## EU-weiter Einsatz (Stand 30.09.2026)

- Schritt „Wo“ bietet alle 27 EU-Staaten. EU-Programme (Funding & Tenders, Erasmus+, AMIF …) erscheinen überall,
  nationale Programme nur im jeweiligen Staat. Deutsche Bundesländer-Filter gibt es nur für Deutschland.
- Nationale Datenbanken mit Importer: **Frankreich** (Aides-territoires; Secret `FN_AIDES_TERRITOIRES_TOKEN`),
  **Spanien** (BDNS, alle staatlichen, regionalen und kommunalen Aufrufe). Beide Endpunkte **nicht live getestet** –
  `python -m importer.run --probe fr|es`. Österreich: Transparenzportal verlinkt, noch kein Importer.
- Die Oberfläche ist deutschsprachig; Texte aus anderen Staaten erscheinen in Originalsprache.

## Städte und Kreise überall in Deutschland

- **Live-Abfrage** im Browser: Ort oder PLZ eingeben, „Verwaltungsleistungen für diesen Ort live abrufen“ fragt das PVOG
  (Bund, Land, Kommune) ab. Ob der Browser das darf (CORS), ist nicht geprüft; sonst erscheint ein Link zur Servicesuche Bund.
- **Nächtlicher Import**: in `importer/sources.yaml` unter `pvog.orte` beliebig viele Orte eintragen.
- **Ratsinformationssysteme (OParl)**: Städte/Kreise mit OParl-Schnittstelle eintragen; neue Förderrichtlinien in
  Beschlussvorlagen werden automatisch als ungeprüfte Hinweise gemeldet.

## Kleine Stiftungen, Preise, kommunale Richtlinien – wie man sie automatisch findet

| Weg | Status |
|---|---|
| PVOG (enthält auch kommunale Leistungen, sofern die Kommune sie pflegt) | eingebaut |
| DSEE-Förderdatenbank (auch Stiftungen und Preise) | eingebaut |
| OParl-Ratsinformationssysteme (neue Förderrichtlinien, Vereinsförderung) | eingebaut, je Ort einzutragen |
| Website-Scraper für Förderseiten von Kreisen, Sparkassen- und Bürgerstiftungen | eingebaut, je Website einzutragen |
| Förder-Newsletter von Kommunen (z. B. „Fördernews“ Berlin-Neukölln, monatlich) als Seiten zum Beobachten | Idee |
| Bundesweites Stiftungsregister beim Bundesamt für Justiz | Start auf 01.01.2028 verschoben; bis dahin Landesverzeichnisse |
| Such-API (z. B. kommerzielle Websuche) mit festen Suchmustern je Kreis | Idee, kostenpflichtig |
| Meldungen von Nutzern und Partnerkommunen | eingebaut |
Vollständigkeit ist bei kleinen Stiftungen nicht erreichbar, weil es keine Pflicht zur Veröffentlichung von Förderangeboten gibt.

## Neu (30.09.2026)

- **Zwei Suchwege:** „Mit Fragen zum Ergebnis“ (Förder-Check für Familien/Privatpersonen und Vereine/Kirchen) oder „Selbst filtern“.
  Die Wahl wird im Browser gemerkt. Der Förder-Check ist eine Vorprüfung mit festen Regeln (`REGELN` in `web/index.template.html`).
- **Neue Daten:** Steuervorteile (§ 35a, § 35c, Übungsleiter-/Ehrenamtspauschale, Kinderbetreuung, Alleinerziehende),
  Pflegeleistungen (Pflegegeld, Entlastungsbetrag, Wohnraumanpassung, Jahresbetrag), KfW 308, 159, 358/359, 261, 297/298, 124, 148 (IKU, auch für gemeinnützige Vereine),
  Bauprogramm Kinder- und Jugendhilfe, evangelikaler Medienfonds, SpardaVereint, Beispiel Vereinsförderung Alsfeld.
- **Kombinationshinweise** an Programmen (Feld `kombi`) und Warnungen im Finanzierungsplan.
- **Kosten- und Finanzierungsplan** mit Deckungslücke, Förderquote, Prüfung bekannter Grenzen, CSV-Export.
- **Mustertexte** für sechs typische Vorhaben; auf Wunsch Abschnitt „Offenheit und Abgrenzung“ für kirchliche Träger.
- **Verwendungsnachweis:** Vorlage Sachbericht + Belegliste je Antrag.
- **Kalender:** Fristen aller gemerkten Programme und Anträge als .ics (einmaliger Export; ein sich selbst aktualisierendes Kalender-Abo bräuchte den Server).
- **Englische Oberfläche** (Navigation, Förder-Check, Suchweg); Förderdaten bleiben in Originalsprache.
- **Datenqualität:** bessere automatische Erkennung von Förderquote/Eigenanteil, Kircheneignung aus Richtlinientexten,
  Dubletten-Erkennung (Alias und Ähnlichkeit), wöchentliche Linkprüfung der Grunddaten (`data/linkcheck.json`).

## Neu (10.11.2026)
- Forschungsförderung: Forschungszulage (Regeln ab 2026) und ZIM als geprüfte Einträge; Förder-Check „Unternehmen / Gründung / Forschung“ mit Forschungszulagen-Rechner
  (geprüft am Rechenbeispiel pandotax: 660.000 € Bemessungsgrundlage → 231.000 € KMU / 165.000 € Nicht-KMU).
- Mustertexte für alle 20 Projektarten.
- Öffentliche Seite ohne Google Fonts: Schriften selbst gehostet (`web/fonts`, SIL Open Font License).
- Handwerkerbonus: geplante Kürzung (Stand 10.11.2026 nicht beschlossen) vermerkt; Wohngeld wegen Reform 2026 auf „teilweise geprüft“ gesetzt.

## Neu (10.11.2026, Teil 2): Bauen, Finanzierung, Kommunen deutschlandweit
- Neue geprüfte Einträge: Wohnungsbauprämie, Wohn-Riester (teilgeprüft, Reform 2027), Denkmal-Abschreibung (§§ 7i, 10f, 11b EStG),
  Sonder-AfA Mietwohnungsneubau (§ 7b), degressive AfA (§ 7 Abs. 5a), Mieterstromzuschlag, WIBank GuW und Hessen-Mikrodarlehen,
  Hessen-Darlehen (teilgeprüft), Bürgschaftsbanken, alle 17 Landesförderbanken (Liste des VÖB).
- Thema „Finanzierung, Kredite, Bürgschaften“; Förder-Check zeigt bei Kauf, Sanierung oder Gründung die Förderbank des Bundeslands.
- **Kommunen-Scraper deutschlandweit** (`importer/sources/kommunen.py`): Verzeichnis aller Gemeinden und Kreise mit Website aus Wikidata
  (Ersatz: OpenStreetMap), je Nacht 300 Kommunen, Startseite + Sitemap, nur Seiten mit Förder- und Antragssignal; Kreis-Einträge gelten
  auch für alle Gemeinden des Kreises. Mit nachgebauten Seiten getestet; **echte Läufe noch nicht getestet**
  (`python -m importer.run --probe kommunen`). Fortschritt: `data/kommunen_state.json`.
- Nicht aufgenommen: Asbestsanierung (kein bundesweites Programm gefunden – nicht recherchiert).

## Neu (16.11.2026): Funktionen nach Wettbewerbsvergleich – alles kostenlos, ohne Server
- Startseite: Fristen-Countdown der nächsten 30 Tage (passend zur Auswahl), Schnelllisten (Frist bald, ohne Eigenanteil, neu, Kleinförderung,
  hohe Summen, Preise, Steuervorteile), Anzahl der Förderungen.
- Passung in Prozent mit „Warum?“ – nachvollziehbare Regeln (Zielgruppe, Region, Thema/Projekt, Bedingungen, Datenqualität), keine KI.
- Suchen speichern (im Browser) mit Hinweis „x neu“, Suche als Link teilen, Ergebnisse und Merkliste als CSV, Drucken/PDF.
- Kostenlose Abos: `fristen.ics` (Kalender-Abo, aktualisiert sich nachts) und `feed.xml` (Newsfeed neuer Förderungen).
- Englische Fassung unter `/en/`, Themenseiten unter `/themen/`, `sitemap.xml`, `robots.txt` für Suchmaschinen.
- Kostenlose Beratungsstellen und weitere Quellen (Aktion Mensch Förderfinder, Stiftungssuche).
- KI-Überarbeitung markiert offene Punkte mit [zu prüfen: …].
Bewusst nicht übernommen (kostenpflichtig oder nur mit Server): E-Mail-Benachrichtigungen, Mandanten/Teams, Experten-Review, PDF-Prüfberichte per KI.
