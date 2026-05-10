"""
News item enrichment - adds context for trading decisions:
- Session timing (premarket / open / after-hours / weekend)
- Prior-day price movement (was the stock already moving?)
- Recent volatility (how big is this move relative to normal?)
"""
import os
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

FINNHUB_TOKEN = os.getenv("FINNHUB_TOKEN", "").strip()
USER_AGENT = "MarketNewsMonitor/1.0"
ET = ZoneInfo("America/New_York")


def get_session_status() -> dict:
    """Returns current US market session status (handles DST automatically)."""
    et_now = datetime.now(ET)
    weekday = et_now.weekday()  # 0=Mon .. 6=Sun

    if weekday >= 5:
        return {
            "label": "WEEKEND",
            "emoji": "⚫",
            "tradeable": False,
            "note": "US markets closed - czekaj do poniedziałku",
        }

    minutes = et_now.hour * 60 + et_now.minute

    if minutes < 4 * 60:
        return {
            "label": "OVERNIGHT",
            "emoji": "🌙",
            "tradeable": False,
            "note": "Przed premarket - bardzo niska płynność",
        }
    if minutes < 9 * 60 + 30:
        return {
            "label": "PREMARKET",
            "emoji": "🟡",
            "tradeable": True,
            "note": "Premarket - mniejsza płynność, szersze spready CFD",
        }
    if minutes < 16 * 60:
        return {
            "label": "OPEN",
            "emoji": "🟢",
            "tradeable": True,
            "note": "Sesja USA otwarta - najlepsza płynność",
        }
    if minutes < 20 * 60:
        return {
            "label": "AFTER_HOURS",
            "emoji": "🔵",
            "tradeable": True,
            "note": "After-hours - niska płynność, szersze spready",
        }
    return {
        "label": "OVERNIGHT",
        "emoji": "🌙",
        "tradeable": False,
        "note": "Po after-hours - czekaj do premarket",
    }


def get_ticker_context(ticker: str) -> dict:
    """Fetch quote + 7-day volatility for a ticker. Returns enrichment dict or {}."""
    if not FINNHUB_TOKEN or not ticker:
        return {}

    ticker = ticker.upper().strip()
    headers = {"User-Agent": USER_AGENT}

    try:
        # Current quote (price, prev close, day's range)
        q = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": FINNHUB_TOKEN},
            timeout=10,
            headers=headers,
        )
        q.raise_for_status()
        quote = q.json()

        current = quote.get("c") or 0
        prev_close = quote.get("pc") or 0
        day_high = quote.get("h") or 0
        day_low = quote.get("l") or 0

        if not current or not prev_close:
            return {}

        today_move_pct = (current - prev_close) / prev_close * 100
        today_range_pct = ((day_high - day_low) / prev_close * 100) if prev_close else 0

        # 7-day daily candles for baseline volatility
        end_ts = int(datetime.now(timezone.utc).timestamp())
        start_ts = end_ts - 7 * 24 * 3600

        c = requests.get(
            "https://finnhub.io/api/v1/stock/candle",
            params={
                "symbol": ticker,
                "resolution": "D",
                "from": start_ts,
                "to": end_ts,
                "token": FINNHUB_TOKEN,
            },
            timeout=10,
            headers=headers,
        )
        candles = {}
        try:
            c.raise_for_status()
            candles = c.json()
        except Exception:
            pass

        avg_daily_range_pct = None
        if candles.get("s") == "ok":
            highs = candles.get("h") or []
            lows = candles.get("l") or []
            closes = candles.get("c") or []
            ranges = []
            for h, l, cl in zip(highs, lows, closes):
                if cl > 0:
                    ranges.append((h - l) / cl * 100)
            if ranges:
                avg_daily_range_pct = sum(ranges) / len(ranges)

        return {
            "ticker": ticker,
            "current_price": round(current, 2),
            "today_move_pct": round(today_move_pct, 2),
            "today_range_pct": round(today_range_pct, 2),
            "avg_daily_range_7d_pct": (
                round(avg_daily_range_pct, 2) if avg_daily_range_pct else None
            ),
        }
    except Exception as e:
        print(f"[enrich] error fetching {ticker}: {e}")
        return {}


def assess_move(ctx: dict) -> str | None:
    """Human-readable assessment of how significant today's move is vs baseline."""
    today = ctx.get("today_move_pct")
    avg = ctx.get("avg_daily_range_7d_pct")
    if today is None:
        return None

    abs_today = abs(today)
    direction = "↑" if today > 0 else ("↓" if today < 0 else "→")

    if not avg or avg == 0:
        return f"{direction}{abs_today:.1f}% dzisiaj"

    multiplier = abs_today / avg
    base = f"{direction}{abs_today:.1f}% dzisiaj ({multiplier:.1f}x avg dnia)"

    if multiplier < 0.5:
        return f"{base} - normalna aktywność"
    if multiplier < 1.5:
        return f"{base} - podwyższona aktywność"
    if multiplier < 3:
        return f"⚠️ {base} - znacznie powyżej normy, news może być częściowo zdyskontowany"
    return f"🚨 {base} - ekstremalny ruch, prawdopodobnie zdyskontowany"


def enrich_alert(item: dict) -> dict:
    """Add session + ticker context to a market-moving news item before alerting."""
    enriched = dict(item)

    # Session timing - no API call
    enriched["session"] = get_session_status()

    # Per-ticker context - 2 Finnhub calls per primary ticker
    tickers = item.get("tickers") or []
    if tickers:
        primary = tickers[0]
        ctx = get_ticker_context(primary)
        if ctx:
            enriched["ticker_context"] = ctx
            enriched["move_assessment"] = assess_move(ctx)

    return enriched
