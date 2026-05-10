"""
News monitor - runs once per cron tick.
Fetches news -> dedupes -> scores via Gemini -> enriches with context -> sends Telegram alerts.
"""
import os
import sys
from sources import fetch_all_news
from analyzer import analyze_news
from notifier import send_telegram_alert
from state import load_seen, save_seen
from enrichment import enrich_alert

URGENCY_THRESHOLD = int(os.getenv("URGENCY_THRESHOLD", "6"))


def main() -> int:
    seen = load_seen()
    raw_items = fetch_all_news()
    print(f"[monitor] fetched {len(raw_items)} items total")

    new_items = [n for n in raw_items if n["id"] not in seen]
    print(f"[monitor] {len(new_items)} new (not seen before)")

    if not new_items:
        save_seen(seen)
        return 0

    # Mark all as seen first - prevents duplicate alerts if a later step crashes
    for item in new_items:
        seen.add(item["id"])
    save_seen(seen)

    BATCH = 25
    sent = 0
    for i in range(0, len(new_items), BATCH):
        batch = new_items[i : i + BATCH]
        analyzed = analyze_news(batch)
        for item in analyzed:
            if not item.get("market_moving"):
                continue
            if int(item.get("urgency", 0)) < URGENCY_THRESHOLD:
                continue

            # Enrich only items that pass the urgency filter (saves Finnhub calls)
            enriched = enrich_alert(item)
            send_telegram_alert(enriched)
            sent += 1

    print(f"[monitor] sent {sent} alerts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
