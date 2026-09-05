"""
Live price updater — AnalystEdge

Reads every currently-open ("Added") pick from data.json, pulls the latest
traded price from Yahoo Finance for each NSE symbol, and writes live.json
which the client dashboard reads for the "Current Price" column.

Runs every 5 minutes during market hours via GitHub Actions. Server-side, so
there is no CORS problem and no public proxy in the chain.

NOTE: earlier versions of this script only fetched prices for the Stock20
watchlist (5 symbols), so open Monthly Picks outside Stock20 never got a
live price and stayed frozen at whatever value was last saved manually.
The Stock20 feature has since been removed entirely, so this version simply
covers every ticker/name of every currently-open pick.
"""

import json
import math
from datetime import datetime, timezone, timedelta

import yfinance as yf

DATA_FILE = "data.json"
OUT_FILE = "live.json"
IST = timezone(timedelta(hours=5, minutes=30))


def clean_symbol(raw):
    s = str(raw).strip().upper()
    if not s:
        return ""
    if " - " in s:
        s = s.split(" - ")[-1].strip()
    s = s.replace("NSE:", "").replace(" ", "")
    if not s:
        return ""
    if not s.endswith(".NS") and not s.endswith(".BO"):
        s = s + ".NS"
    return s


def safe_num(v):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def fetch_price(symbol):
    """Return (price, previous_close). Falls back to intraday history."""
    t = yf.Ticker(symbol)
    price = prev = None

    try:
        fi = t.fast_info
        price = safe_num(getattr(fi, "last_price", None))
        prev = safe_num(getattr(fi, "previous_close", None))
    except Exception:
        pass

    if price is None:
        try:
            info = t.info or {}
            price = safe_num(info.get("currentPrice")) or safe_num(info.get("regularMarketPrice"))
            prev = prev or safe_num(info.get("previousClose"))
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

    return price, prev


def looks_like_ticker(raw):
    """Filter out obvious full company names (e.g. 'Akums Drugs and
    Pharmaceuticals Ltd') so we don't waste Yahoo lookups on strings that
    can never be a valid NSE symbol. Real tickers are short, no more than
    a couple of words."""
    s = str(raw or "").strip()
    if not s or len(s) > 20:
        return False
    if len(s.split()) > 2:
        return False
    return True


def collect_symbols(data):
    """Ticker + name of every currently-open pick."""
    raw_symbols = []

    for p in data.get("picks") or []:
        if p.get("action") != "Added":
            continue  # Booked/Removed picks keep their frozen exit price on purpose
        if looks_like_ticker(p.get("ticker")):
            raw_symbols.append(p["ticker"])
        if looks_like_ticker(p.get("name")):
            raw_symbols.append(p["name"])

    return raw_symbols


def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    raw_symbols = collect_symbols(data)

    # Dedupe by cleaned Yahoo symbol, keep first raw form for logging.
    seen = {}
    for raw in raw_symbols:
        sym = clean_symbol(raw)
        if sym and sym not in seen:
            seen[sym] = raw

    quotes = {}
    for sym, raw in seen.items():
        key = sym.replace(".NS", "").replace(".BO", "")
        try:
            price, prev = fetch_price(sym)
            if price is None:
                print("SKIP %s (%s): no price" % (sym, raw))
                continue
            entry = {"price": round(price, 2)}
            if prev:
                entry["prevClose"] = round(prev, 2)
                entry["dayPct"] = round((price - prev) / prev * 100, 2)
            quotes[key] = entry
            print("OK  %s: %s" % (sym, entry["price"]))
        except Exception as e:
            print("FAIL %s: %s" % (sym, e))

    now = datetime.now(timezone.utc)
    out = {
        "updatedAt": now.isoformat(),
        "updatedIST": now.astimezone(IST).strftime("%d %b %Y, %I:%M:%S %p"),
        "quotes": quotes,
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("Wrote %s with %d quotes." % (OUT_FILE, len(quotes)))


if __name__ == "__main__":
    main()
