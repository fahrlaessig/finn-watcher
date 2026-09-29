#!/usr/bin/env python3
"""
history.py

Baut aus state.json einen dauerhaften Verlauf je Konfiguration (history.json)
und erzeugt daraus das Dashboard (docs/index.html) fuer GitHub Pages.

Laeuft im Workflow direkt NACH finn_watcher.py. finn_watcher.py selbst
bleibt unveraendert.

Gespeichert werden nur Ereignisse, nicht jeder Lauf:
  neu     - Konfiguration taucht zum ersten Mal auf
  preis   - Preis hat sich geaendert
  verf    - nur die Verfuegbarkeit hat sich geaendert
  weg     - Konfiguration ist nicht mehr im Angebot
  wieder  - Konfiguration ist nach einer Pause wieder da (Wiedereinstieg)

Beim allerersten Lauf (history.json existiert noch nicht) wird der Verlauf
automatisch aus der Git-Historie von state.json rekonstruiert. Dafuer muss
der Workflow mit 'fetch-depth: 0' auschecken.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

STATE_FILE = os.environ.get("STATE_FILE", "state.json")
HISTORY_FILE = os.environ.get("HISTORY_FILE", "history.json")
TEMPLATE_FILE = "dashboard_template.html"
OUTPUT_FILE = os.path.join("docs", "index.html")

# Ab diesem Tag (deutsche Zeit) wird der Verlauf gefuehrt. Alles davor
# (z.B. Testlaeufe) wird ignoriert. Wird der Wert geaendert, baut sich
# history.json beim naechsten Lauf automatisch neu aus der Git-Historie auf.
HISTORY_START = "2026-09-14"
START_TS = datetime.fromisoformat(HISTORY_START).replace(tzinfo=ZoneInfo("Europe/Berlin"))


def log(msg):
    print(f"[history] {msg}", flush=True)


def to_int(p):
    if p is None:
        return None
    digits = re.sub(r"[^\d]", "", str(p))
    return int(digits) if digits else None


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_history():
    return {"version": 1, "start": HISTORY_START, "last_update": None, "cars": {}}


def apply_snapshot(history, state, ts):
    """Vergleicht einen Stand (state.json-Inhalt) mit dem Verlauf und
    haengt erkannte Ereignisse an. Leere Staende werden ignoriert."""
    if not state:
        return 0
    cars = history["cars"]
    events = 0

    for cid, c in state.items():
        if not isinstance(c, dict):
            continue
        price = to_int(c.get("price"))
        avail = c.get("availability")
        meta = {k: v for k, v in c.items() if k not in ("price", "availability")}
        entry = cars.get(cid)

        if entry is None:
            cars[cid] = {
                "meta": meta,
                "present": True,
                "price": price,
                "avail": avail,
                "events": [{"t": ts, "e": "neu", "p": price, "a": avail}],
            }
            events += 1
            continue

        entry["meta"] = meta
        if not entry["present"]:
            entry["events"].append({"t": ts, "e": "wieder", "p": price, "a": avail})
            events += 1
        elif price != entry["price"]:
            entry["events"].append({"t": ts, "e": "preis", "p": price, "a": avail})
            events += 1
        elif avail != entry["avail"]:
            entry["events"].append({"t": ts, "e": "verf", "p": price, "a": avail})
            events += 1
        entry.update(present=True, price=price, avail=avail)

    for cid, entry in cars.items():
        if entry["present"] and cid not in state:
            entry["events"].append({"t": ts, "e": "weg", "p": entry["price"], "a": None})
            entry["present"] = False
            events += 1

    history["last_update"] = ts
    return events


def backfill_from_git(history):
    """Spielt alle bisherigen Versionen von state.json aus der Git-Historie
    der Reihe nach ein."""
    try:
        out = subprocess.run(
            ["git", "log", "--reverse", "--format=%H %cI", "--", STATE_FILE],
            capture_output=True, text=True, check=True,
        ).stdout
    except Exception as e:
        log(f"Git-Historie nicht lesbar ({e}) - starte ohne Rueckblick.")
        return

    commits = [line.split(" ", 1) for line in out.strip().splitlines() if line]
    log(f"Rekonstruiere Verlauf aus {len(commits)} Commits von {STATE_FILE} ...")
    for sha, ts in commits:
        try:
            raw = subprocess.run(
                ["git", "show", f"{sha}:{STATE_FILE}"],
                capture_output=True, text=True, check=True,
            ).stdout
            state = json.loads(raw)
        except Exception:
            continue
        dt = datetime.fromisoformat(ts)
        if dt < START_TS:
            continue
        ts = dt.astimezone(timezone.utc).isoformat()
        apply_snapshot(history, state, ts)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build_dashboard(history):
    if not os.path.exists(TEMPLATE_FILE):
        log(f"{TEMPLATE_FILE} fehlt - Dashboard wird nicht erzeugt.")
        return
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()
    data = json.dumps(history, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/")  # sicher im <script>-Block
    html = template.replace("/*__DATA__*/null", data)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    # GitHub Pages soll die Datei 1:1 ausliefern (kein Jekyll)
    open(os.path.join("docs", ".nojekyll"), "a").close()
    log(f"Dashboard geschrieben: {OUTPUT_FILE}")


def main():
    history = load_json(HISTORY_FILE, None)
    if history is None or history.get("start") != HISTORY_START:
        log(f"Baue Verlauf neu auf (Start: {HISTORY_START}).")
        history = new_history()
        backfill_from_git(history)

    state = load_json(STATE_FILE, {})
    n = apply_snapshot(history, state, now_iso())
    log(f"{n} neue Ereignisse, {len(history['cars'])} Konfigurationen im Verlauf.")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)

    build_dashboard(history)


if __name__ == "__main__":
    main()
