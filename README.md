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
5. Ab dem nächsten planmäßigen Lauf (oder erneutem manuellen Start)
   bekommst du bei echten Änderungen Telegram-Nachrichten.

## Zeitplan

Der Workflow läuft automatisch, du musst nichts manuell anstoßen. Aktuell
eingestellt: stündlich zur Minute `:07` (nicht `:00` – siehe unten),
zwischen 07:00 und 19:00 **UTC** (`.github/workflows/finn-watch.yml`,
`cron: "7 7-19 * * *"`).

- **UTC statt Ortszeit:** GitHub-Cron kennt keine Zeitzonen. 07:00-19:00 UTC
  entspricht ca. 08:00-20:00 Uhr deutscher Zeit im Winter (CET) bzw.
  09:00-21:00 Uhr im Sommer (CEST) – das Fenster verschiebt sich zweimal
  im Jahr durch die Zeitumstellung um eine Stunde.
- **Minute `:07` statt `:00`:** GitHub selbst empfiehlt, geplante Workflows
  nicht exakt auf die volle Stunde zu legen, da das der weltweit beliebteste
  Zeitpunkt für Cron-Jobs ist und es dadurch zu Verzögerungen kommen kann.
- **Nachtpause:** Bewusst eingebaut, um im kostenlosen GitHub-Actions-
  Kontingent (2.000 Minuten/Monat für private Repos) zu bleiben – siehe
  nächster Abschnitt.

Intervall/Zeitfenster ändern: die `cron`-Zeile in `finn-watch.yml` anpassen,
z.B. `"7 6-20 * * *"` für 06:00-20:00 UTC.

## Kosten / GitHub-Actions-Minuten

Das Skript selbst kostet nichts – es nutzt keine Claude-/AI-Tokens, sondern
läuft als reiner Python-Code auf GitHub-Servern. Verbraucht wird lediglich
**GitHub-Actions-Rechenzeit**:

- Privates Repo, GitHub-Free-Plan: **2.000 Minuten/Monat kostenlos**
- Ein Durchlauf dauert ca. 4,5 Minuten (3 Teil-Suchen: Haupt, Kupplung, HUD)
- Bei 13 Läufen/Tag (aktuelles 07-19-Uhr-Fenster, stündlich):
  13 × 30 × 4,5 ≈ **1.755 Minuten/Monat** → passt bequem ins Kontingent

GitHub-Konten haben standardmäßig ein **Ausgabenlimit von 0 $**: Wird das
Kontingent doch mal überschritten, pausiert GitHub die Läufe einfach bis
zum Monatswechsel – es entstehen **keine** unerwarteten Kosten, außer du
hinterlegst selbst aktiv eine Zahlungsmethode mit höherem Limit.

Willst du die Frequenz ändern (z.B. weniger Nachtpause oder öfter am Tag),
im Kopf behalten: Laufzeit (~4,5 Min) × Läufe/Tag × 30 sollte unter 2.000
bleiben.

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
