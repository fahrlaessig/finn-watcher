#!/usr/bin/env python3
"""
finn_watcher.py

Beobachtet eine gefilterte finn.com Auto-Abo-Suche (z.B.
https://www.finn.com/de-DE/subscribe/elektro?is_for_business=true&...)
auf Veraenderungen im Angebot:

  - ein Fahrzeug/eine Konfiguration ist nicht mehr verfuegbar
  - ein Fahrzeug/eine Konfiguration ist neu dazugekommen
  - der Preis einer Konfiguration hat sich geaendert

Bei jeder erkannten Aenderung wird eine EINZELNE Telegram-Nachricht
pro betroffenem Fahrzeug/Konfiguration verschickt.

Der letzte bekannte Stand wird in einer JSON-Datei (STATE_FILE)
gespeichert, damit beim naechsten Lauf verglichen werden kann.

Benoetigte Umgebungsvariablen:
  FINN_URL             Die gefilterte finn.com Such-URL
  TELEGRAM_BOT_TOKEN   Bot-Token von @BotFather
  TELEGRAM_CHAT_ID     Chat-ID, an die Nachrichten gesendet werden

Optional:
  STATE_FILE           Pfad zur State-Datei (Default: state.json)
  DEBUG                Wenn gesetzt (z.B. "1"), wird zusaetzlicher
                        Debug-Output ausgegeben und der rohe extrahierte
                        Text jeder Modellseite in debug_output/ abgelegt.
"""

import json
import os
import re
import sys
import time
import hashlib
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.finn.com"

FINN_URL = os.environ.get("FINN_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
DEBUG = os.environ.get("DEBUG", "").strip() not in ("", "0", "false", "False")

COOKIE_BUTTON_TEXTS = [
    "Alle akzeptieren",
    "Akzeptieren",
    "Accept all",
    "Alle Cookies akzeptieren",
    "Einverstanden",
]


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def debug_dump(name: str, content: str):
    if not DEBUG:
        return
    os.makedirs("debug_output", exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)[:120]
    with open(os.path.join("debug_output", safe + ".txt"), "w", encoding="utf-8") as f:
        f.write(content)


def accept_cookies_if_present(page):
    for text in COOKIE_BUTTON_TEXTS:
        try:
            btn = page.get_by_text(text, exact=False)
            if btn.count() > 0:
                btn.first.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def scroll_to_load_all(page, max_rounds=20, pause_ms=900):
    """Scrollt wiederholt ans Seitenende, um Lazy-Loading / 'Mehr laden'
    Buttons auszuloesen, bis sich die Anzahl der Modell-Links nicht mehr
    aendert oder max_rounds erreicht ist."""
    last_count = -1
    stable_rounds = 0
    for _ in range(max_rounds):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(pause_ms)

        # Falls es einen "Mehr laden" / "Load more" Button gibt, klicken
        for text in ["Mehr laden", "Mehr anzeigen", "Load more", "Weitere Fahrzeuge"]:
            try:
                btn = page.get_by_text(text, exact=False)
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click(timeout=1500)
                    page.wait_for_timeout(pause_ms)
            except Exception:
                pass

        count = page.locator('a[href*="/de-DE/models/"]').count()
        if count == last_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        last_count = count
        if stable_rounds >= 2:
            break
    return last_count


def extract_model_links(page):
    """Extrahiert alle eindeutigen Modell-Links (href) von der
    gefilterten Listing-Seite."""
    links = page.locator('a[href*="/de-DE/models/"]')
    n = links.count()
    seen = {}
    for i in range(n):
        href = links.nth(i).get_attribute("href")
        if not href:
            continue
        full = urljoin(BASE_URL, href)
        # Modellname (Brand/Modell) aus dem Pfad ableiten fuer sauberes Dedup
        seen[full.split("?")[0]] = full  # behalte die Version MIT Query-Params
    return list(seen.values())


CONFIG_BLOCK_SPLIT_MARKER = "Vergleichen"

# Erkennt Zeilen wie: "Benzin143 kW (194 PS)Automatik" oder "Elektro150 kW (204 PS)Automatik"
FUEL_POWER_RE = re.compile(
    r"(?P<fuel>Benzin|Diesel|Elektro|Hybrid|Plug-In-Hybrid|Vollhybrid)"
    r"\s*(?P<power>\d+\s*kW\s*\(\d+\s*PS\))"
    r"\s*(?P<transmission>Automatik|Manuell)",
    re.IGNORECASE,
)

PRICE_RE = re.compile(
    r"(\d{2,4}(?:[.,]\d{3})?)\s*€\s*\n?\s*(?:pro Monat|im Monat)",
    re.IGNORECASE,
)

AVAILABILITY_RE = re.compile(
    r"(Vsl\.\s*Übergabe\s*[\d.]+\s*-\s*[\d.]+|Schnell verfügbar|Sofort verfügbar)"
)

RANGE_RE = re.compile(r"(\d{2,4})\s*km Reichweite")
CONSUMPTION_RE = re.compile(
    r"(?:Energieverbrauch|Kraftstoffverbrauch)\s*\(kombiniert\):\s*([\d.,]+)\s*(kWh|l)/100\s*km",
    re.IGNORECASE,
)
DRIVE_RE = re.compile(
    r"(Frontantrieb|Heckantrieb|Allradantrieb|All-Wheel Drive|Front-Wheel Drive|Rear-Wheel Drive)",
    re.IGNORECASE,
)
INTERIOR_COLOR_RE = re.compile(r"Innenfarbe:?\s*([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-/ ]{2,40})")
HITCH_RE = re.compile(r"Anhängerkupplung", re.IGNORECASE)


def parse_model_configs(model_name: str, model_url: str, full_text: str):
    """Parst den sichtbaren Text einer Modell-Detailseite in einzelne
    Fahrzeug-Konfigurationen. Arbeitet bewusst text-basiert (statt ueber
    CSS-Klassen), da diese sich bei finn.com aendern koennen.

    Wichtig: Es wird NICHT mehr auf den "Vergleichen"-Button als Trenner
    zwischen Konfigurationen gesetzt, da dieser bei Modellen mit nur EINER
    Konfiguration gar nicht angezeigt wird. Stattdessen wird direkt nach
    dem Muster "Kraftstoff + Leistung + Getriebe" gesucht, das bei jeder
    Konfiguration vorkommt - das ist zuverlaessiger."""

    matches = list(FUEL_POWER_RE.finditer(full_text))
    configs = []

    for i, fp_match in enumerate(matches):
        fuel = fp_match.group("fuel")
        power = re.sub(r"\s+", " ", fp_match.group("power")).strip()
        transmission = fp_match.group("transmission")

        # Trim-Name: die letzte nicht-leere Zeile VOR diesem Match
        before = full_text[: fp_match.start()]
        lines = [l.strip() for l in before.splitlines() if l.strip()]
        trim = lines[-1] if lines else "Unbekannte Ausstattung"
        trim = re.sub(r"^\d+\s*$", "", trim).strip()
        if not trim and len(lines) > 1:
            trim = lines[-2]
        if not trim:
            trim = "Unbekannte Ausstattung"

        # Suchfenster NACH diesem Match bis zum naechsten Match (oder Textende)
        window_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        window = full_text[fp_match.end():window_end]

        avail_match = AVAILABILITY_RE.search(window)
        availability = avail_match.group(1) if avail_match else "Unbekannt"

        price_match = PRICE_RE.search(window)
        price = price_match.group(1).replace(".", "") if price_match else None

        range_match = RANGE_RE.search(window)
        range_km = range_match.group(1) if range_match else None

        cons_match = CONSUMPTION_RE.search(window)
        consumption = f"{cons_match.group(1)} {cons_match.group(2)}/100km" if cons_match else None

        # Antriebsart als Fallback direkt aus dem Konfigurationsnamen ableiten
        # (z.B. "... RWD Premium" oder "... AWD Select"); die genauere Variante
        # kommt spaeter ggf. von der individuellen Auto-Detailseite.
        drive = None
        if re.search(r"\bAWD\b", trim, re.IGNORECASE):
            drive = "Allradantrieb (AWD)"
        elif re.search(r"\bRWD\b", trim, re.IGNORECASE):
            drive = "Heckantrieb (RWD)"
        elif re.search(r"\bFWD\b", trim, re.IGNORECASE):
            drive = "Frontantrieb (FWD)"

        key_raw = f"{model_url.split('?')[0]}|{trim}|{fuel}|{power}|{transmission}"
        config_id = hashlib.sha1(key_raw.encode("utf-8")).hexdigest()[:16]

        configs.append(
            {
                "id": config_id,
                "model_name": model_name,
                "model_url": model_url.split("?")[0],
                "trim": trim,
                "fuel": fuel,
                "power": power,
                "transmission": transmission,
                "availability": availability,
                "price": price,  # als String in Euro, z.B. "269", oder None wenn nicht gefunden
                "range_km": range_km,
                "consumption": consumption,
                "drive": drive,
            }
        )

    return configs


def fetch_current_offers(page, finn_url: str):
    """Crawlt eine gefilterte finn.com-Such-URL komplett (alle passenden
    Modelle und deren Konfigurationen). Nutzt eine von aussen uebergebene
    Playwright-'page', damit der Browser fuer mehrere Durchlaeufe
    (Haupt-Suche + Attribut-Filter-Suchen) wiederverwendet werden kann."""

    log(f"Lade Listing-Seite: {finn_url}")
    page.goto(finn_url, wait_until="domcontentloaded", timeout=45000)
    accept_cookies_if_present(page)
    page.wait_for_timeout(3000)

    scroll_to_load_all(page)
    debug_dump("listing_page", page.inner_text("body"))

    model_links = extract_model_links(page)
    log(f"{len(model_links)} Modell-Links gefunden.")

    all_configs = {}
    for idx, model_url in enumerate(model_links, start=1):
        try:
            log(f"[{idx}/{len(model_links)}] Lade Modellseite: {model_url}")
            page.goto(model_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)  # Zeit fuer nachgeladene Preise

            body_text = page.inner_text("body")

            # "Aehnliche Modelle"-Empfehlungsbereich (andere Autos!) abschneiden,
            # damit dessen Preise nicht versehentlich der letzten Konfiguration
            # dieser Seite zugeordnet werden.
            cutoff = body_text.find("Ähnliche Modelle")
            if cutoff != -1:
                body_text = body_text[:cutoff]

            debug_dump(f"model_{idx}", body_text)

            # Modellname aus H1 oder aus URL ableiten
            model_name = model_url.rstrip("/").split("/")[-1].replace("-", " ").title()
            try:
                h1 = page.locator("h1").first
                if h1.count() > 0:
                    text = h1.inner_text().strip()
                    if text:
                        model_name = text
            except Exception:
                pass

            configs = parse_model_configs(model_name, model_url, body_text)
            log(f"  -> {len(configs)} Konfiguration(en) erkannt")
            for c in configs:
                log(
                    f"     - {c['trim']} | {c['fuel']} | {c['transmission']} "
                    f"| Preis: {c['price']} | Verfuegbarkeit: {c['availability']} "
                    f"| Antrieb: {c.get('drive')}"
                )
                all_configs[c["id"]] = c
        except Exception as e:
            log(f"  Fehler bei {model_url}: {e}")
            continue

    return all_configs


def load_previous_state():
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("WARNUNG: Telegram-Zugangsdaten fehlen, Nachricht wird nicht gesendet:")
        log(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            log(f"Telegram-Fehler ({resp.status_code}): {resp.text}")
    except Exception as e:
        log(f"Telegram-Sendefehler: {e}")


def fmt_price(p):
    return f"{p} €/Monat" if p else "Preis unbekannt"


def fmt_price_change(old_p, new_p):
    """Formatiert eine Preisaenderung inkl. Richtung (Pfeil) und Prozent."""
    if old_p is None or new_p is None:
        return f"💶 Preis: {fmt_price(old_p)} → {fmt_price(new_p)}"
    try:
        old_i = int(old_p)
        new_i = int(new_p)
    except ValueError:
        return f"💶 Preis: {fmt_price(old_p)} → {fmt_price(new_p)}"

    diff = new_i - old_i
    pct = (diff / old_i * 100) if old_i else 0.0

    if diff > 0:
        arrow, sign = "📈", "+"
    elif diff < 0:
        arrow, sign = "📉", ""
    else:
        arrow, sign = "➡️", ""

    return (
        f"💶 Preis: {old_i}€ → {new_i}€ {arrow} "
        f"({sign}{diff}€, {sign}{pct:.1f}%)"
    )


def format_car_label(c: dict) -> str:
    return f"{c['model_name']} – {c['trim']}"


def format_details_block(c: dict) -> str:
    """Baut den ausfuehrlichen Detail-Block (Leistung, Getriebe, Verbrauch,
    Reichweite, Antrieb, Innenfarbe, Kupplung) - laesst fehlende Werte weg,
    statt falsche/unsichere Angaben zu machen."""
    lines = [f"🔧 {c['power']} · {c['transmission']} · {c['fuel']}"]

    if c.get("drive"):
        lines.append(f"⚙️ Antriebsart: {c['drive']}")

    if c.get("range_km"):
        lines.append(f"🔋 Reichweite (WLTP): {c['range_km']} km")

    if c.get("consumption"):
        lines.append(f"⚡ Verbrauch (kombiniert): {c['consumption']}")

    if c.get("interior_color"):
        lines.append(f"🎨 Innenfarbe: {c['interior_color']}")

    if c.get("hitch"):
        lines.append(f"🚗 Anhängerkupplung: {c['hitch']}")

    return "\n".join(lines)


def diff_and_notify(old_state: dict, new_state: dict):
    old_ids = set(old_state.keys())
    new_ids = set(new_state.keys())

    removed = old_ids - new_ids
    added = new_ids - old_ids
    common = old_ids & new_ids

    # Alle zu verschickenden Nachrichten zuerst sammeln (mit Modellname/Ausstattung
    # als Sortierschluessel), statt sie sofort zu senden. So koennen wir sie vor
    # dem eigentlichen Versand nach Modell gruppieren, statt sie in der
    # zufaelligen internen Reihenfolge (neu/weg/geaendert getrennt) zu schicken.
    events = []  # Liste von (model_name, trim, text)

    for cid in added:
        c = new_state[cid]
        text = (
            f"🆕 Neues Angebot verfügbar\n\n"
            f"{format_car_label(c)}\n"
            f"{format_details_block(c)}\n\n"
            f"💶 Preis: {fmt_price(c['price'])}\n"
            f"📅 Verfügbarkeit: {c['availability']}\n\n"
            f"{c['model_url']}"
        )
        events.append((c["model_name"], c["trim"], text))

    for cid in removed:
        c = old_state[cid]
        text = (
            f"❌ Angebot nicht mehr verfügbar\n\n"
            f"{format_car_label(c)}\n"
            f"{format_details_block(c)}\n\n"
            f"💶 Letzter bekannter Preis: {fmt_price(c['price'])}\n\n"
            f"{c['model_url']}"
        )
        events.append((c["model_name"], c["trim"], text))

    for cid in common:
        old_c = old_state[cid]
        new_c = new_state[cid]

        # Bewusste Entscheidung: Nur echte PREISaenderungen loesen eine
        # Nachricht aus. Aenderungen der voraussichtlichen Uebergabezeit
        # allein (die relativ haeufig vorkommen, aber im ersten Wurf nicht
        # interessieren) werden ignoriert.
        if old_c.get("price") != new_c.get("price"):
            text = (
                f"🔄 Angebot geändert\n\n"
                f"{format_car_label(new_c)}\n"
                f"{format_details_block(new_c)}\n\n"
                f"{fmt_price_change(old_c.get('price'), new_c.get('price'))}\n"
                f"📅 Verfügbarkeit: {new_c['availability']}\n\n"
                f"{new_c['model_url']}"
            )
            events.append((new_c["model_name"], new_c["trim"], text))

    # Nach Modellname (und innerhalb eines Modells nach Ausstattungslinie)
    # sortieren, damit alle Nachrichten zu einem Fahrzeugmodell hintereinander
    # ankommen, statt durcheinander.
    events.sort(key=lambda e: (e[0], e[1]))

    for _, _, text in events:
        send_telegram_message(text)

    return len(events)


def main():
    if not FINN_URL:
        log("FEHLER: Umgebungsvariable FINN_URL ist nicht gesetzt.")
        sys.exit(1)

    old_state = load_previous_state()
    log(f"Bisheriger Stand: {len(old_state)} bekannte Konfigurationen.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="de-DE")
        page = context.new_page()

        log("=== Hauptsuche ===")
        new_state = fetch_current_offers(page, FINN_URL)

        # Verbindungszeichen fuer den zusaetzlichen Filter-Parameter bestimmen
        # (& falls die URL schon einen ? hat, sonst neu mit ? anfangen)
        sep = "&" if "?" in FINN_URL else "?"

        hitch_url = f"{FINN_URL}{sep}features=hitch"

        log("=== Zusatz-Suche: Anhängerkupplung ===")
        hitch_ids = set(fetch_current_offers(page, hitch_url).keys())

        browser.close()

    log(
        f"Aktueller Stand: {len(new_state)} Konfigurationen gefunden "
        f"({len(hitch_ids)} mit Anhängerkupplung)."
    )

    for cid, c in new_state.items():
        c["hitch"] = "Ja" if cid in hitch_ids else "Nein"

    if not new_state:
        log(
            "WARNUNG: Es wurden 0 Konfigurationen gefunden. Um einen "
            "kompletten Fehl-Alarm (alle Autos 'verschwunden') zu vermeiden, "
            "wird der State in diesem Fall NICHT ueberschrieben und es "
            "werden keine Benachrichtigungen verschickt. Bitte pruefen, "
            "ob sich an der Seite etwas geaendert hat."
        )
        sys.exit(2)

    if not old_state:
        log("Kein vorheriger Stand vorhanden (vermutlich erster Lauf) - "
            "es werden keine Benachrichtigungen verschickt, nur der "
            "aktuelle Stand wird gespeichert.")
        save_state(new_state)
        return

    n = diff_and_notify(old_state, new_state)
    log(f"{n} Benachrichtigung(en) verschickt.")

    save_state(new_state)


if __name__ == "__main__":
    main()
