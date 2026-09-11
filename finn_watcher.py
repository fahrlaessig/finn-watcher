#!/usr/bin/env python3
"""
finn_watcher.py

Beobachtet eine gefilterte finn.com Auto-Abo-Suche (z.B.
https://www.finn.com/de-DE/subscribe/elektro?is_for_business=true&...)
auf Veraenderungen im Angebot:

  - ein Fahrzeug/eine Konfiguration ist nicht mehr verfuegbar
  - ein Fahrzeug/eine Konfiguration ist neu dazugekommen
  - der Preis einer Konfiguration hat sich geaendert
  - die Verfuegbarkeit (voraussichtliche Uebergabe) hat sich geaendert

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

PRICE_RE = re.compile(r"(?:ab\s*)?(\d{2,4}(?:[.,]\d{3})?)\s*€")

AVAILABILITY_RE = re.compile(
    r"(Vsl\.\s*Übergabe\s*[\d.]+\s*-\s*[\d.]+|Schnell verfügbar|Sofort verfügbar)"
)


def parse_model_configs(model_name: str, model_url: str, full_text: str):
    """Parst den sichtbaren Text einer Modell-Detailseite in einzelne
    Fahrzeug-Konfigurationen. Arbeitet bewusst text-basiert (statt ueber
    CSS-Klassen), da diese sich bei finn.com aendern koennen."""

    blocks = full_text.split(CONFIG_BLOCK_SPLIT_MARKER)
    configs = []

    for block in blocks[1:]:  # erstes Element ist Text vor der ersten Config
        fp_match = FUEL_POWER_RE.search(block)
        if not fp_match:
            continue

        fuel = fp_match.group("fuel")
        power = re.sub(r"\s+", " ", fp_match.group("power")).strip()
        transmission = fp_match.group("transmission")

        # Trim-Name: die Zeile direkt vor dem Fuel/Power-Match
        before = block[: fp_match.start()]
        lines =
