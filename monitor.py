"""
News monitor - BREAKING NEWS ONLY edition.

Hard filters applied in this order:
  1. Source-level freshness (sources.py - MAX_AGE_MINUTES)
  2. AI must mark market_moving=true
  3. Direction must be 'up' or 'down' (no 'unclear')
  4. Must have at least one ticker
  5. Urgency must meet URGENCY_THRESHOLD
"""
import os
import sys
from sources import fetch_all_news
from analyzer import analyze_news
from notifier import send_telegram_alert
from state import load_seen, save_seen
from enrichment import enrich_alert

URGENCY_THRESHOLD = int(os.getenv("URGENCY_THRESHOLD", "6"))


def passes_quality_filter(item: dict) -> tuple[bool, str]:
    """Returns (passes, reason_if_rejected) for diagnostics."""
    if not item.get("market_moving"):
        return False, "not market_moving"
    direction = item.get("direction")
    if direction not in ("up", "down"):
        return False, f"direction not clear ({direction})"
    tickers = item.get("tickers") or []
    if not tickers:
        return False, "no ticker"
    urgency = int(item.get("urgency", 0))
    if urgency < URGENCY_THRESHOLD:
        return False, f"urgency {urgency} below threshold {URGENCY_THRESHOLD}"
    return True, ""


def main() -> int:
    seen = load_seen()
    raw_items = fetch_all_news()
    print(f"[monitor] fetched {len(raw_items)} items total")

    new_items = [n for n in raw_items if n["id"] not in seen]
    print(f"[monitor] {len(new_items)} new (not seen before)")

    if not new_items:
        save_seen(seen)
        return 0

    # Mark all as seen first - prevents duplicate alerts on later crashes
    for item in new_items:
        seen.add(item["id"])
    save_seen(seen)

    BATCH = 25
    sent = 0
    rejected = 0
    for i in range(0, len(new_items), BATCH):
        batch = new_items[i : i + BATCH]
        analyzed = analyze_news(batch)
        for item in analyzed:
            ok, reason = passes_quality_filter(item)
            if not ok:
                rejected += 1
                continue

            # Enrich only items that passed all filters (saves Finnhub calls)
            enriched = enrich_alert(item)
            send_telegram_alert(enriched)
            sent += 1

    print(f"[monitor] sent {sent} alerts, rejected {rejected} items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
