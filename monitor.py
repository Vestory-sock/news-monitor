"""
News monitor - PHASE 1 QUALITY EDITION.

Hard filters applied in this order:
  1. Source-level freshness (sources.py - MAX_AGE_MINUTES)
  2. Asian ADR blacklist (analyzer.py - pre-filter)
  3. AI must mark market_moving=true (Gemini analyzer)
  4. Direction must be 'up' or 'down' (no 'unclear')
  5. Must have at least one ticker
  6. Urgency must meet URGENCY_THRESHOLD
  7. Price-news sanity check (NEW in Phase 1):
     - During OPEN session: high urgency requires meaningful price reaction
     - Price moving against thesis direction = reject
"""
import os
import sys
from sources import fetch_all_news
from analyzer import analyze_news
from notifier import send_telegram_alert
from state import load_seen, save_seen
from enrichment import enrich_alert

URGENCY_THRESHOLD = int(os.getenv("URGENCY_THRESHOLD", "6"))

# Sanity check thresholds
SANITY_MIN_MOVE_OPEN_PCT = 0.3      # below this in OPEN session = no market reaction
SANITY_AGAINST_THESIS_PCT = 1.0     # if price moves >1% against direction = reject


def passes_quality_filter(item: dict) -> tuple[bool, str]:
    """Returns (passes, reason_if_rejected) for diagnostics."""
    if not item.get("market_moving"):
        reason = item.get("rejection_reason") or "not market_moving"
        return False, reason
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


def passes_sanity_check(enriched_item: dict) -> tuple[bool, str]:
    """
    Sanity check based on actual price movement.

    Rules:
    - If session is OPEN and urgency >= 7 but price hasn't moved >0.3% → reject
      (market is open and reacting to news, lack of movement = no material impact)
    - If price moved >1% in OPPOSITE direction to thesis → reject
      (market disagrees with bot's interpretation)

    Returns (passes, reason_if_rejected).
    """
    session = enriched_item.get("session") or {}
    session_label = session.get("label", "")
    direction = enriched_item.get("direction")
    urgency = int(enriched_item.get("urgency", 0))

    ctx = enriched_item.get("ticker_context") or {}
    today_move = ctx.get("today_move_pct")

    # If we don't have price data, can't sanity check - let it through
    if today_move is None:
        return True, ""

    # Check 1: Price moving AGAINST thesis direction in any session
    if direction == "up" and today_move < -SANITY_AGAINST_THESIS_PCT:
        return False, f"sanity: bullish thesis but price ↓{abs(today_move):.1f}% (market disagrees)"
    if direction == "down" and today_move > SANITY_AGAINST_THESIS_PCT:
        return False, f"sanity: bearish thesis but price ↑{abs(today_move):.1f}% (market disagrees)"

    # Check 2: High urgency + OPEN session + no reaction = false positive
    if session_label == "OPEN" and urgency >= 7 and abs(today_move) < SANITY_MIN_MOVE_OPEN_PCT:
        return False, f"sanity: urgency {urgency} but only {today_move:+.1f}% in OPEN session (no reaction)"

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

    # Mark all as seen first - prevents duplicates on crashes
    for item in new_items:
        seen.add(item["id"])
    save_seen(seen)

    BATCH = 25
    sent = 0
    rejected_quality = 0
    rejected_sanity = 0
    for i in range(0, len(new_items), BATCH):
        batch = new_items[i : i + BATCH]
        analyzed = analyze_news(batch)
        for item in analyzed:
            ok, reason = passes_quality_filter(item)
            if not ok:
                rejected_quality += 1
                continue

            # Enrich only items that passed quality filter
            enriched = enrich_alert(item)

            # Sanity check on actual price data
            sane, sanity_reason = passes_sanity_check(enriched)
            if not sane:
                print(f"[monitor] rejected by sanity: {sanity_reason} | "
                      f"{enriched.get('tickers')} | {enriched.get('headline','')[:60]}")
                rejected_sanity += 1
                continue

            send_telegram_alert(enriched)
            sent += 1

    print(f"[monitor] sent {sent} alerts | rejected: {rejected_quality} quality, {rejected_sanity} sanity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
