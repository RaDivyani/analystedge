"""
Hourly Current Price updater — AnalystEdge

Unlike update_live.py (which writes a separate live.json that only affects
what a visitor's browser shows *while they're looking at the page*), this
script writes the fetched price PERMANENTLY into data.json itself — into
each open ("Added") pick's currentPrice and returnPct fields — and commits
that. So even if nobody's browser ever fetches live.json, the stored
Current Price stays accurate, and manual data-entry mistakes (like a wrong
number typed into the price field) get overwritten with a real price on
the very next run.

Runs once an hour during market hours via GitHub Actions. Booked/Removed
picks are never touched — their exit price is frozen on purpose.
"""

import json
import math
from datetime import datetime, timezone, timedelta

import yfinance as yf

DATA_FILE = "data.json"
IST = timezone(timedelta(hours=5, minutes=30))

# Same corrections list as update_live.py — keep both in sync whenever a
# stock's ticker/name doesn't match its real NSE symbol on Yahoo Finance.
SYMBOL_FIXES = {
    "JAYNECO": "JAYNECOIND",  # Jayaswal Neco Industries Ltd
}


def clean_symbol(raw):
    s = str(raw).strip().upper()
    if not s:
        return ""
    if " - " in s:
        s = s.split(" - ")[-1].strip()
    s = s.replace("NSE:", "").replace(" ", "")
    if not s:
        return ""
    if s.endswith(".NS") or s.endswith(".BO"):
        base, suffix = s[:-3], s[-3:]
    else:
        base, suffix = s, ".NS"
    base = SYMBOL_FIXES.get(base, base)
    return base + suffix


def looks_like_ticker(raw):
    s = str(raw or "").strip()
    if not s or len(s) > 20:
        return False
    if len(s.split()) > 2:
        return False
    return True


def pick_symbol(p):
    """Best-guess real NSE symbol for one pick: prefer the ticker field,
    fall back to name, else None (can't safely guess)."""
    if looks_like_ticker(p.get("ticker")):
        return clean_symbol(p["ticker"])
    if looks_like_ticker(p.get("name")):
        return clean_symbol(p["name"])
    return None


def safe_num(v):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def fetch_price(symbol):
    t = yf.Ticker(symbol)
    price = None
    try:
        fi = t.fast_info
        price = safe_num(getattr(fi, "last_price", None))
    except Exception:
        pass
    if price is None:
        try:
            info = t.info or {}
            price = safe_num(info.get("currentPrice")) or safe_num(info.get("regularMarketPrice"))
        except Exception:
            pass
    if price is None:
        try:
            hist = t.history(period="1d", interval="1m")
            closes = hist["Close"].dropna()
            if len(closes):
                price = safe_num(closes.iloc[-1])
        except Exception:
            pass
    return price


def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    picks = data.get("picks") or []
    open_picks = [p for p in picks if p.get("action") == "Added"]

    # symbol -> list of open picks that resolve to it (usually just one)
    by_symbol = {}
    for p in open_picks:
        sym = pick_symbol(p)
        if sym:
            by_symbol.setdefault(sym, []).append(p)
        else:
            print("SKIP (no usable ticker/name): %s" % p.get("name"))

    changed = 0
    for sym, plist in by_symbol.items():
        try:
            price = fetch_price(sym)
        except Exception as e:
            print("FAIL %s: %s" % (sym, e))
            continue
        if price is None:
            print("SKIP %s: no price" % sym)
            continue
        price = round(price, 2)
        for p in plist:
            old = p.get("currentPrice")
            p["currentPrice"] = price
            price_added = safe_num(p.get("priceAdded"))
            if price_added:
                p["returnPct"] = (price - price_added) / price_added * 100
            if old != price:
                changed += 1
            print("OK  %s (%s): %s -> %s" % (sym, p.get("name"), old, price))

    if changed:
        now = datetime.now(timezone.utc)
        data["updatedAt"] = now.isoformat()
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print("Updated %d pick(s), wrote %s." % (changed, DATA_FILE))
    else:
        print("No changes.")


if __name__ == "__main__":
    main()
