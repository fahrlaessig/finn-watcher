# FINN Angebots-Watcher

Überwacht eine gefilterte finn.com Auto-Abo-Suche und schickt dir per
Telegram eine Nachricht, sobald sich am Angebot etwas ändert:

- ✅ neue Konfiguration/neues Fahrzeug verfügbar
- ❌ Konfiguration nicht mehr verfügbar
- 🔄 Preis oder Verfügbarkeit einer Konfiguration hat sich geändert

Läuft stündlich automatisch über GitHub Actions (kostenlos), du musst
dafür keinen eigenen Rechner laufen lassen.

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
5. Im Browser aufrufen (Token einsetzen):
   `https://api.telegram.org/bot<DEIN_TOKEN>/getUpdates`
   In der JSON-Antwort die **Chat-ID** unter `"chat":{"id": ...}` suchen.

### 3. Secrets & Variablen im Repository hinterlegen

Im Repository unter **Settings → Secrets and variables → Actions**:

**Secrets** (Tab "Secrets", Klick auf "New repository secret"):
| Name | Wert |
|---|---|
| `TELEGRAM_BOT_TOKEN` | dein Bot-Token |
| `TELEGRAM_CHAT_ID` | deine Chat-ID |

**Variables** (Tab "Variables", Klick auf "New repository variable"):
| Name | Wert |
|---|---|
| `FINN_URL` | deine gefilterte finn.com-Such-URL, z.B. `https://www.finn.com/de-DE/subscribe/elektro?is_for_business=true&max_price_msrp=65000&mileage_package=1000&monthly_payment_of_service_fee=true&sort=asc` |

### 4. Ersten Lauf starten

1. Im Repository auf den Reiter **Actions** gehen.
2. Links den Workflow **"FINN Angebots-Watcher"** auswählen.
3. Rechts auf **"Run workflow"** klicken, um ihn einmal manuell zu starten.
4. Im Log prüfen, ob Konfigurationen gefunden wurden ("X Konfiguration(en)
   gefunden"). Beim allerersten Lauf wird noch **keine** Telegram-Nachricht
   verschickt (es gibt ja noch nichts zum Vergleichen) – es wird nur der
   aktuelle Stand in `state.json` gespeichert und automatisch committet.
5. Ab dem zweiten Lauf (automatisch jede volle Stunde, oder erneut manuell
   ausgelöst) bekommst du bei Änderungen Telegram-Nachrichten.

## Anpassen

- **Prüfintervall ändern:** In `.github/workflows/finn-watch.yml` die
  Zeile `cron: "0 * * * *"` anpassen (z.B. `*/30 * * * *` für alle 30 Min.).
- **Andere Filter/URL:** Einfach die `FINN_URL`-Variable in den Repository-
  Settings ändern (z.B. neue Filter direkt auf finn.com einstellen und die
  URL aus der Adresszeile kopieren).
- **Debug-Modus:** Workflow-Datei um `DEBUG: "1"` als env-Variable ergänzen,
  dann wird der erkannte Text jeder Seite unter `debug_output/` abgelegt
  (hilfreich, falls sich an der Seitenstruktur von finn.com etwas ändert
  und die Erkennung angepasst werden muss).

## Bekannte Einschränkungen

- Es handelt sich um einen Scraper der öffentlichen Webseite (keine
  offizielle API) – ändert finn.com seine Seitenstruktur grundlegend,
  kann eine Anpassung des Skripts nötig werden.
- Fahrzeuge/Konfigurationen werden anhand von Modell + Ausstattungslinie +
  Kraftstoff + Leistung + Getriebe identifiziert (es gibt auf der
  öffentlichen Seite keine sichtbare eindeutige Fahrzeug-ID wie eine VIN).
  In seltenen Fällen könnten dadurch zwei technisch identische, aber
  eigentlich unterschiedliche Fahrzeuge als "ein" Angebot behandelt werden.
- Bitte das Prüfintervall moderat halten (stündlich ist unkritisch), um
  finn.com nicht unnötig zu belasten.
