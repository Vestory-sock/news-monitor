"""Telegram notifier - Polish labels, enriched context."""
import os
import html
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DIRECTION_EMOJI = {
    "up": "🟢 ↑",
    "down": "🔴 ↓",
}


def send_telegram_alert(item: dict) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("[telegram] BOT_TOKEN/CHAT_ID not configured, skipping send")
        return

    direction = item.get("direction", "up")
    arrow = DIRECTION_EMOJI.get(direction, "🟢 ↑")
    urgency = int(item.get("urgency", 0))
    fire = "🔥" * min(urgency, 10)

    tickers = item.get("tickers") or []
    ticker_line = " ".join(f"${t.upper()}" for t in tickers if t) or "MARKET"

    headline = html.escape(item.get("headline", ""))
    reason = html.escape(item.get("reason", ""))
    source = html.escape(item.get("source", ""))
    url = item.get("url", "")

    session = item.get("session") or {}
    session_emoji = session.get("emoji", "")
    session_label = session.get("label", "")
    session_note = session.get("note", "")

    move_assessment = item.get("move_assessment")
    ticker_context = item.get("ticker_context") or {}
    current_price = ticker_context.get("current_price")

    text = f"{arrow}  <b>{ticker_line}</b>  |  Pilność: <b>{urgency}/10</b> {fire}\n"

    if session_label:
        text += f"{session_emoji} <b>{session_label}</b>: {html.escape(session_note)}\n"

    text += f"\n<b>{headline}</b>\n\n"

    if reason:
        text += f"💡 <i>{reason}</i>\n"

    if move_assessment:
        text += f"📊 {html.escape(move_assessment)}"
        if current_price:
            text += f"  |  cena ${current_price}"
        text += "\n"

    text += f"\n📰 {source}"
    if url:
        text += f"  |  <a href=\"{url}\">otwórz</a>"

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=15,
        )
        if r.status_code != 200:
            print(f"[telegram] HTTP {r.status_code}: {r.text[:200]}")
        else:
            print(f"[telegram] sent: {ticker_line} u={urgency}")
    except Exception as e:
        print(f"[telegram] error: {e}")
