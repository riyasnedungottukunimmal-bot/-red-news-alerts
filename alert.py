#!/usr/bin/env python3
"""
Forex Factory red-folder news alerts for GitHub Actions.

Each run checks the free Forex Factory weekly feed, sends a phone alert
(ntfy and/or Telegram) for high-impact events that are close, and records
what it sent in state.json so you never get duplicates.

Settings come from environment variables (set in alert.yml / GitHub Secrets).
"""
import json
import os
import time
import datetime as dt
import urllib.request
from zoneinfo import ZoneInfo

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
STATE_FILE = "state.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
CURRENCIES = [c.strip().upper() for c in os.environ.get("CURRENCIES", "").split(",") if c.strip()]
LEADS = sorted(int(x) for x in (os.environ.get("LEAD_MINUTES") or "30,5").split(",") if x.strip())
try:
    TZ = ZoneInfo((os.environ.get("TIMEZONE") or "UTC").strip())
except Exception:
    TZ = ZoneInfo("UTC")


def http(url, data=None, headers=None):
    h = {"User-Agent": "Mozilla/5.0 (ff-red-news-alert)"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def send(title, body):
    ok = False
    if NTFY_TOPIC:
        try:
            http(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                body.encode("utf-8"),
                {
                    "Title": title.encode("ascii", "ignore").decode() or "Red news",
                    "Priority": "5",
                    "Tags": "red_circle",
                },
            )
            ok = True
        except Exception as ex:
            print("ntfy error:", ex)
    if TG_TOKEN and TG_CHAT:
        try:
            payload = json.dumps(
                {"chat_id": TG_CHAT, "text": f"\U0001F534 {title}\n{body}"}
            ).encode("utf-8")
            http(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                payload,
                {"Content-Type": "application/json"},
            )
            ok = True
        except Exception as ex:
            print("Telegram error:", ex)
    if not ok:
        print("No notification channel worked. Check your secrets.")
    return ok


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def main():
    if os.environ.get("TEST", "").lower() == "true":
        send("TEST: Red news alert works", "GitHub Actions setup is correct.")
        if not os.path.exists(STATE_FILE):
            save_state({})
        return

    state = load_state()
    original = dict(state)
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = time.time() - 3 * 86400
    state = {k: v for k, v in state.items() if v > cutoff}

    try:
        events = json.loads(http(FEED_URL))
    except Exception as ex:
        print("Feed error (will retry next run):", ex)
        events = []

    for e in events:
        if e.get("impact") != "High":
            continue
        if CURRENCIES and e.get("country") not in CURRENCIES:
            continue
        try:
            t = dt.datetime.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        mins = (t - now).total_seconds() / 60
        if mins <= 0:
            continue
        bucket = next((lead for lead in LEADS if mins <= lead), None)
        if bucket is None:
            continue
        key = f'{e["title"]}|{e["date"]}|{bucket}'
        if key in state:
            continue
        local = t.astimezone(TZ).strftime("%a %H:%M")
        body = (
            f'{e["country"]} in {int(mins)} min ({local} {TZ.key})\n'
            f'Forecast: {e.get("forecast") or "-"} | Previous: {e.get("previous") or "-"}'
        )
        if send(e["title"], body):
            state[key] = time.time()

    if state != original or not os.path.exists(STATE_FILE):
        save_state(state)


if __name__ == "__main__":
    main()
