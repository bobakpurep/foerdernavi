# Fördernavi kostenlos auf GitHub betreiben – fürs Handy, ohne Anmeldung

Ergebnis: eine feste Adresse wie `https://IHR-NAME.github.io/foerdernavi/`. Jede Nacht holt GitHub neue Daten
(Förderdatenbank des Bundes, EU) und aktualisiert die Seite. Nutzer brauchen kein Konto.
Einrichtung einmalig, ca. 15 Minuten, **am besten am PC** (Hochladen vieler Dateien geht am Handy schlecht).

## 1. Konto und Repository
1. Auf https://github.com kostenlos registrieren.
2. Oben rechts **+ → New repository**. Name: `foerdernavi`. **Public** auswählen
   (nach meinem Wissen gibt es GitHub Pages im Gratis-Tarif nur für öffentliche Repositories).
   Häkchen „Add a README“ setzen, dann **Create repository**.

## 2. Dateien hochladen
1. Das ZIP entpacken. Den **Inhalt** des Ordners `fordernavi` verwenden (nicht den Ordner selbst).
2. Im Repository **Add file → Upload files**, alle Dateien und Ordner ins Fenster ziehen, unten **Commit changes**.
3. **Wichtig:** Der Ordner `.github` ist auf Mac und Windows oft unsichtbar und wird dann nicht mit hochgeladen.
   Prüfen: Gibt es im Repository den Ordner `.github/workflows`? Falls nicht:
   **Add file → Create new file**, als Namen genau `.github/workflows/import-und-veroeffentlichen.yml` eintippen,
   den Inhalt der gleichnamigen Datei aus dem ZIP hineinkopieren, **Commit changes**.

## 3. Veröffentlichung einschalten
1. **Settings → Pages**, bei „Build and deployment → Source“ **GitHub Actions** wählen.
2. **Settings → Actions → General → Workflow permissions**: „Read and write permissions“ wählen, speichern.
3. Optional: **Settings → Secrets and variables → Actions → Variables → New repository variable**,
   Name `MELDE_EMAIL`, Wert Ihre E-Mail. Dann schickt „Förderung melden“ die Meldung per E-Mail an Sie.

## 4. Erster Lauf
1. Reiter **Actions → „Daten importieren und veröffentlichen“ → Run workflow**.
2. Nach einigen Minuten grüner Haken. Die Adresse steht unter **Settings → Pages**.
3. Im Schritt „Förderdaten importieren“ steht, wie viele Einträge jede Quelle geliefert hat. Bei einem Fehler
   bleiben die Grunddaten erhalten; die Fehlermeldung steht auch in `data/import.log.json` und in der Fußzeile der Seite.

## 5. Aufs Handy
Adresse im Handybrowser öffnen:
- **iPhone (Safari):** Teilen-Symbol → „Zum Home-Bildschirm“.
- **Android (Chrome):** Menü ⋮ → „App installieren“ bzw. „Zum Startbildschirm hinzufügen“.
Danach startet Fördernavi wie eine App und funktioniert auch ohne Netz mit dem zuletzt geladenen Stand.
Merkliste und Anträge bleiben auf dem jeweiligen Handy (Export-Knopf unter „Anträge“ als Sicherung).

## Quellen ein- und ausschalten
Datei `importer/sources.yaml` im Repository öffnen → Stift-Symbol → `enabled: true/false` ändern → Commit.
Die DSEE (`dsee:`) ist aus. **Erst nach Freigabe durch die DSEE einschalten.**

## Was diese Variante nicht kann
Keine Nutzerkonten, keine Synchronisierung zwischen Geräten, kein Redaktionsbereich im Browser – dafür braucht es
den eigenen Server (siehe README). Datenkorrekturen: `data/programme.seed.json` im Repository bearbeiten.

## Grenzen und Pflichten (Einschätzung, nicht geprüft)
- GitHub pausiert zeitgesteuerte Abläufe in öffentlichen Repositories nach längerer Inaktivität (nach meinem Wissen 60 Tage)
  und schickt dann eine E-Mail; mit einem Klick im Reiter Actions wieder einschalten.
- Ein öffentliches Angebot in Deutschland braucht in der Regel ein Impressum: Platzhalter im Reiter „Impressum“
  in `web/index.template.html` ausfüllen.
- Die Seite lädt Schriften von Google Fonts. Für ein öffentliches Angebot besser entfernen oder selbst hosten (siehe README).
