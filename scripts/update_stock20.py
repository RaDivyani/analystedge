"""
Stock20 auto-updater — AnalystEdge
Reads the stock20 symbol list from data.json (published by admin.html),
fetches latest market data from Yahoo Finance for each NSE symbol,
and writes stock20.json which the client dashboard renders.

Runs daily after market close via GitHub Actions. No login needed.
"""

import json
import math
import time
from datetime import datetime, timezone

import yfinance as yf

DATA_FILE = "data.json"
OUT_FILE = "stock20.json"


def clean_symbol(raw):
    """Normalize whatever the admin typed into an NSE Yahoo symbol."""
    s = str(raw).strip().upper()
    # Allow entries like "DCBBANK", "DCBBANK.NS", "NSE:DCBBANK", "DCB Bank - DCBBANK"
    if " - " in s:
        s = s.split(" - ")[-1].strip()
    s = s.replace("NSE:", "").replace(" ", "")
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


def fetch_one(symbol):
    t = yf.Ticker(symbol)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}

    hist = None
    try:
        hist = t.history(period="1y", auto_adjust=True)
    except Exception:
        hist = None

    price = safe_num(info.get("currentPrice")) or safe_num(info.get("regularMarketPrice"))
    prev = safe_num(info.get("previousClose")) or safe_num(info.get("regularMarketPreviousClose"))

    day_pct = None
    m1_pct = None
    trend = None
    w52_low = safe_num(info.get("fiftyTwoWeekLow"))
    w52_high = safe_num(info.get("fiftyTwoWeekHigh"))

    if hist is not None and len(hist) > 0:
        closes = hist["Close"].dropna()
        if price is None and len(closes) > 0:
            price = safe_num(closes.iloc[-1])
        if prev is None and len(closes) > 1:
            prev = safe_num(closes.iloc[-2])
        # 1-month return (~21 trading days)
        if len(closes) > 22 and price:
            base = safe_num(closes.iloc[-22])
            if base:
                m1_pct = round((price - base) / base * 100, 2)
        # 52w range fallback
        if w52_low is None and len(closes) > 0:
            w52_low = safe_num(closes.min())
        if w52_high is None and len(closes) > 0:
            w52_high = safe_num(closes.max())
        # Trend from 50 & 200 DMA
        if price and len(closes) >= 50:
            dma50 = safe_num(closes.tail(50).mean())
            dma200 = safe_num(closes.tail(200).mean()) if len(closes) >= 200 else None
            if dma50:
                above50 = price > dma50
                above200 = (price > dma200) if dma200 else above50
                if above50 and above200:
                    trend = "Uptrend"
                elif not above50 and not above200:
                    trend = "Downtrend"
                else:
                    trend = "Sideways"

    if day_pct is None and price and prev:
        day_pct = round((price - prev) / prev * 100, 2)

    name = info.get("longName") or info.get("shortName") or symbol.replace(".NS", "")

    div_yield = safe_num(info.get("dividendYield"))
    # yfinance sometimes returns fraction (0.012) and sometimes percent (1.2)
    if div_yield is not None and div_yield < 0.5:
        div_yield = round(div_yield * 100, 2)
    elif div_yield is not None:
        div_yield = round(div_yield, 2)

    return {
        "symbol": symbol.replace(".NS", "").replace(".BO", ""),
        "name": name,
        "price": round(price, 2) if price else None,
        "dayPct": day_pct,
        "m1Pct": m1_pct,
        "w52Low": round(w52_low, 2) if w52_low else None,
        "w52High": round(w52_high, 2) if w52_high else None,
        "mktCap": safe_num(info.get("marketCap")),
        "pe": round(safe_num(info.get("trailingPE")), 1) if safe_num(info.get("trailingPE")) else None,
        "pb": round(safe_num(info.get("priceToBook")), 1) if safe_num(info.get("priceToBook")) else None,
        "divYield": div_yield,
        "trend": trend,
    }


def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    symbols = data.get("stock20") or []
    if not symbols:
        print("stock20 list is empty in data.json — nothing to do.")
        # still write an empty file so the client hides the section cleanly
        out = {"updatedAt": datetime.now(timezone.utc).isoformat(), "stocks": []}
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        return

    stocks = []
    for raw in symbols:
        sym = clean_symbol(raw)
        try:
            row = fetch_one(sym)
            stocks.append(row)
            print(f"OK  {sym}: {row['price']}")
        except Exception as e:
            print(f"FAIL {sym}: {e}")
            stocks.append({
                "symbol": sym.replace(".NS", ""),
                "name": str(raw),
                "price": None, "dayPct": None, "m1Pct": None,
                "w52Low": None, "w52High": None, "mktCap": None,
                "pe": None, "pb": None, "divYield": None, "trend": None,
            })
        time.sleep(1.5)  # be polite to Yahoo

    out = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "stocks": stocks,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Wrote {OUT_FILE} with {len(stocks)} stocks.")


if __name__ == "__main__":
    main()
