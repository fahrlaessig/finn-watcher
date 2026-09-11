# FINN Angebots-Watcher

Überwacht eine gefilterte finn.com Auto-Abo-Suche und schickt dir per
Telegram eine Nachricht, sobald sich am Angebot etwas ändert:

- 🆕 neue Konfiguration/neues Fahrzeug verfügbar
- ❌ Konfiguration nicht mehr verfügbar
- 🔄 Preis (inkl. Richtung & Prozent) oder Verfügbarkeit einer Konfiguration
  hat sich geändert

Läuft automatisch über GitHub Actions nach festem Zeitplan – kein eigener
Rechner nötig, kein manuelles Anstoßen.

## Was eine Nachricht enthält

Jede Nachricht bezieht sich auf **eine einzelne Konfiguration** (Modell +
Ausstattungslinie + Antrieb/Getriebe) und enthält, soweit auf finn.com
verfügbar:

- Modell und Ausstattungslinie
- Leistung, Getriebe, Kraftstoff
- Antriebsart (Front-/Heck-/Allradantrieb, wo ermittelbar)
- Elektrische Reichweite (WLTP) bzw. Verbrauch (kombiniert)
- Anhängerkupplung: Ja/Nein
- Head-up-Display: Ja/Nein
- Preis (bei Änderungen inkl. 📈/📉-Richtung und Prozent)
- Voraussichtliche Verfügbarkeit/Übergabe
- Link zur Modellseite

Kommen bei einem Lauf mehrere Nachrichten auf einmal, werden sie **nach
Fahrzeugmodell gruppiert** verschickt (alle Nachrichten zu einem Modell
hintereinander), nicht durcheinander gemischt.

## Wie die Ausstattungs-Erkennung funktioniert

Anhängerkupplung und Head-up-Display lassen sich auf der Fahrzeug-Detailseite
selbst nicht zuverlässig auslesen. Stattdessen nutzt das Skript FINNs eigene
Filter-Funktion: Es crawlt zusätzlich zur Hauptsuche noch zwei weitere,
gefilterte Suchen (`&features=hitch` bzw. `&features=head_up_display`) und
vergleicht, welche Konfigurationen dort ebenfalls auftauchen. Taucht eine
Konfiguration in der Hauptliste, aber nicht in der Kupplungs-Liste auf, hat
sie keine Kupplung – und umgekehrt. Das ist zuverlässiger als Text-Suche auf
Unterseiten.

Ein Nebeneffekt: Ein einzelner Durchlauf besucht dadurch **dreimal** die
komplette Modell-Liste (Haupt-, Kupplungs- und HUD-Suche), was die Laufzeit
auf ca. 4-5 Minuten verlängert.

**Fahrassistenz-Level und Innenfarbe** werden bewusst NICHT angezeigt:
FINN veröffentlicht keine standardisierte Assistenzstufe, und die Innenfarbe
ist auf der öffentlichen Seite nirgends zuverlässig auslesbar, ohne für
jedes einzelne Auto eine eigene Detail-/Checkout-Seite zu öffnen (deutlich
aufwändiger, in einem Test ohne Erfolg).

## Einmalige Einrichtung

### 1. Repository erstellen

1. Erstelle auf [github.com](https://github.com) ein neues, **privates**
   Repository (z.B. `finn-watcher`).
2. Lade alle Dateien aus diesem Ordner in das Repository hoch
   (per "Add file" → "Upload files" im Browser, oder per `git push`,
   wenn du mit Git vertraut bist).

### 2. Telegram-Bot einrichten

1. In Telegram nach `@BotFather` suchen, Chat starten.
2. `/newbot` senden, Namen und Username vergeben.
3. Den erhaltenen **Bot-Token** notieren (Format `123456789:ABC...`).
4. Deinem neuen Bot in Telegram eine beliebige Nachricht schreiben
   (z.B. "Hallo"), damit er weiß, wohin er antworten darf.
5. Chat-ID herausfinden – entweder:
   - im Browser `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates`
     aufrufen und nach `"chat":{"id": ...}` suchen, oder
   - in Telegram den Bot **@userinfobot** anschreiben, er nennt dir direkt
     deine Nutzer-/Chat-ID.

### 3. Secrets & Variablen im Repository hinterlegen

Im Repository unter **Settings → Secrets and variables → Actions**:

**Secrets** (Tab "Secrets", "New repository secret"):
| Name | Wert |
|---|---|
| `TELEGRAM_BOT_TOKEN` | dein Bot-Token |
| `TELEGRAM_CHAT_ID` | deine Chat-ID |

**Variables** (Tab "Variables", "New repository variable"):
| Name | Wert |
|---|---|
| `FINN_URL` | deine gefilterte finn.com-Such-URL, z.B. `https://www.finn.com/de-DE/subscribe/elektro?is_for_business=true&max_price_msrp=65000&mileage_package=1500&monthly_payment_of_service_fee=true&sort=asc` |

Wichtig: `FINN_URL` sollte **keinen** eigenen `features=`-Parameter
enthalten – die zwei Zusatzsuchen (Kupplung/HUD) hängt das Skript selbst an.

### 4. Ersten Lauf starten

1. Im Repository auf **Actions** gehen.
2. Links **"FINN Angebots-Watcher"** auswählen.
3. Rechts auf **"Run workflow"** klicken (manueller Start).
4. Im Log prüfen: "X Konfiguration(en) gefunden" pro Modell, am Ende
   "Aktueller Stand: Y Konfigurationen gefunden (Z mit Anhängerkupplung,
   W mit Head-up-Display)". Beim allerersten Lauf kommt noch **keine**
   Telegram-Nachricht (nichts zum Vergleichen da) – nur der Ist-Zustand
   wird in `state.json` gespeichert und automatisch committet.
5. Ab dem nächsten planmäßigen Lauf (ausgelöst durch den externen Trigger,
   siehe nächster Abschnitt, oder erneutem manuellen Start) bekommst du bei
   echten Änderungen Telegram-Nachrichten.

### 5. Externen Trigger einrichten

Damit der Watcher auch automatisch läuft, ohne dass du selbst auf
"Run workflow" klicken musst: siehe Abschnitt **"Zeitplan / Trigger"**
weiter unten (cron-job.org-Einrichtung).

## Zeitplan / Trigger

**Wichtig:** GitHubs eigener `schedule`-Trigger hat sich bei diesem Repository
als unzuverlässig erwiesen (bekannte, in der GitHub-Community mehrfach
dokumentierte Plattform-Eigenheit: geplante Workflows feuern manchmal trotz
korrekter Konfiguration einfach nicht). Deshalb läuft der Watcher **nicht**
über `on: schedule`, sondern wird von einem **externen, kostenlosen
Cron-Dienst ([cron-job.org](https://cron-job.org))** ausgelöst, der stündlich
per GitHub-API einen `workflow_dispatch`-Aufruf macht. Vorteil nebenbei:
cron-job.org läuft direkt in deiner eigenen Zeitzone (z.B. Europe/Berlin) –
kein Umrechnen auf UTC nötig, keine Zeitumstellungs-Verschiebung.

### Einmalige Einrichtung des externen Triggers

**1. GitHub-Zugangstoken erstellen** (damit cron-job.org den Workflow starten
darf):
1. GitHub → Profilbild → Settings → ganz unten "Developer settings"
2. "Personal access tokens" → "Fine-grained tokens" → "Generate new token"
3. Name z.B. `finn-watcher-trigger`, Ablaufdatum wählen, Repository access
   → "Only select repositories" → `finn-watcher`
4. Unter "Repository permissions" → "Actions" auf **"Read and write"**
   stellen, sonst nichts
5. "Generate token" klicken, den Token (`github_pat_...`) sofort sicher
   speichern (wird danach nie wieder angezeigt)
6. **Ablaufdatum im Kalender vormerken** – nach Ablauf muss ein neuer Token
   erstellt und bei cron-job.org eingetragen werden, sonst bleiben die
   automatischen Läufe wieder aus

**2. Cronjob bei cron-job.org anlegen:**
- Kostenlosen Account erstellen
- Neuer Cronjob mit:
  - **URL:** `https://api.github.com/repos/<DEIN_GITHUB_USERNAME>/finn-watcher/actions/workflows/finn-watch.yml/dispatches`
  - **Request method:** `POST`
  - **Headers:**
    | Key | Value |
    |---|---|
    | `Authorization` | `Bearer <DEIN_TOKEN>` |
    | `Accept` | `application/vnd.github+json` |
    | `Content-Type` | `application/json` |
  - **Request body:** `{"ref":"main"}`
  - **Time zone:** deine eigene (z.B. `Europe/Berlin`)
  - **Zeitplan:** stündlich, nur zwischen z.B. 08:00 und 20:00 Uhr

Der Token gehört ausschließlich in das Header-Feld bei cron-job.org – niemals
in eine Datei im Repository oder sonst irgendwo veröffentlichen.

### Woran man erkennt, welcher Trigger gefeuert hat

In GitHub unter Actions steht bei jedem Lauf, wer/was ihn ausgelöst hat:
- **"Manually run by \<dein Name\>"** → du selbst über den "Run workflow"-Button
- **kein "Manually run by..." bzw. Auslöser ist ein Token/App** → externer
  Trigger von cron-job.org via API

Ein manueller Test-Klick auf "Run workflow" funktioniert weiterhin jederzeit
zusätzlich, unabhängig vom externen Trigger.

### Frequenz/Zeitfenster ändern

Einfach den Zeitplan im cron-job.org-Dashboard anpassen (Uhrzeit-Fenster,
Intervall) – keine Code- oder Repository-Änderung nötig.

## Kosten / GitHub-Actions-Minuten

Das Skript selbst kostet nichts – es nutzt keine Claude-/AI-Tokens, sondern
läuft als reiner Python-Code auf GitHub-Servern. Verbraucht wird lediglich
**GitHub-Actions-Rechenzeit** (unabhängig davon, ob der Lauf über den
externen Trigger oder manuell gestartet wurde):

- Privates Repo, GitHub-Free-Plan: **2.000 Minuten/Monat kostenlos**
- Ein Durchlauf dauert ca. 4,5 Minuten (3 Teil-Suchen: Haupt, Kupplung, HUD)
- Bei 13 Läufen/Tag (aktuelles 08-20-Uhr-Fenster, stündlich):
  13 × 30 × 4,5 ≈ **1.755 Minuten/Monat** → passt bequem ins Kontingent

GitHub-Konten haben standardmäßig ein **Ausgabenlimit von 0 $**: Wird das
Kontingent doch mal überschritten, schlagen die von cron-job.org
ausgelösten `workflow_dispatch`-Aufrufe fehl bzw. GitHub startet den Job
einfach nicht, bis zum Monatswechsel – es entstehen **keine** unerwarteten
Kosten, außer du hinterlegst selbst aktiv eine Zahlungsmethode mit höherem
Limit.

Willst du die Frequenz ändern (z.B. weniger Nachtpause oder öfter am Tag),
im Kopf behalten: Laufzeit (~4,5 Min) × Läufe/Tag × 30 sollte unter 2.000
bleiben – Anpassung erfolgt im cron-job.org-Zeitplan, nicht im Code.

## Anpassen

- **Filter ändern:** Einfach die `FINN_URL`-Variable in den Repository-
  Settings ändern (neue Filter auf finn.com einstellen, URL aus der
  Adresszeile kopieren, `is_for_business`/`mileage_package`/etc. je nach
  Bedarf anpassen).
- **Nachrichtenformat ändern:** In `finn_watcher.py` die Funktionen
  `format_details_block()` (welche Details angezeigt werden) und
  `diff_and_notify()` (Nachrichtentext/Aufbau) anpassen.
- **Debug-Modus:** Workflow-Datei um `DEBUG: "1"` als env-Variable im
  Schritt "Watcher ausfuehren" ergänzen, dann wird der erkannte Text jeder
  Seite unter `debug_output/` abgelegt (hilfreich bei Erkennungsproblemen).

## Bekannte Einschränkungen

- Scraper der öffentlichen Webseite (keine offizielle API) – ändert
  finn.com seine Seitenstruktur grundlegend, kann eine Anpassung nötig sein.
  Bereits mehrfach vorgekommen: geänderter Preis-Anzeige-Ort, Rabatt-Texte,
  die versehentlich als Preis erkannt wurden, "Ähnliche Modelle"-Bereich
  am Seitenende mit fremden Preisen.
- Fahrzeuge/Konfigurationen werden anhand von Modell + Ausstattungslinie +
  Kraftstoff + Leistung + Getriebe identifiziert (keine sichtbare
  eindeutige Fahrzeug-ID wie eine VIN auf der öffentlichen Seite).
- Innenfarbe und ein standardisiertes Fahrassistenz-Level sind nicht
  verfügbar (siehe oben).
- Bei sehr vielen Konfigurationen auf einer Modellseite kann die Zuordnung
  von Trim-Namen in Einzelfällen ungenau sein (text-basierte Erkennung statt
  über feste HTML-Struktur, da sich CSS-Klassen bei finn.com ändern können).
