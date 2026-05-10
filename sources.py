"""
News fetchers - BREAKING NEWS ONLY edition.

Strict freshness: items older than MAX_AGE_MINUTES (default 10) are dropped.
Only primary sources (press release wires + SEC) and fastest media feeds.

Each function returns a list of dicts with fields:
  id, headline, summary, source, url, published, tickers (list[str], may be empty)
"""
import os
import hashlib
import time
from datetime import datetime, timezone, timedelta

import requests
import feedparser

FINNHUB_TOKEN = os.getenv("FINNHUB_TOKEN", "").strip()
USER_AGENT = "MarketNewsMonitor/2.0 (research; personal use)"

# Strict freshness filter - items older than this are discarded BEFORE Gemini sees them
MAX_AGE_MINUTES = int(os.getenv("MAX_AGE_MINUTES", "10"))


def _hid(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cutoff() -> datetime:
    return _now() - timedelta(minutes=MAX_AGE_MINUTES)


# ---------- Finnhub general news ----------
def fetch_finnhub_general() -> list[dict]:
    if not FINNHUB_TOKEN:
        print("[finnhub] no token, skipping")
        return []
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_TOKEN},
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[finnhub] error: {e}")
        return []

    items = []
    cutoff_ts = _cutoff().timestamp()
    for n in data[:80]:
        ts = n.get("datetime", 0)
        if ts < cutoff_ts:
            continue
        related = n.get("related", "") or ""
        tickers = [t.strip() for t in related.split(",") if t.strip()]
        items.append({
            "id": _hid("finnhub", str(n.get("id", "")), n.get("url", "")),
            "headline": (n.get("headline") or "").strip(),
            "summary": (n.get("summary") or "")[:600],
            "source": n.get("source") or "Finnhub",
            "url": n.get("url", ""),
            "published": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "tickers": tickers,
        })
    print(f"[finnhub] {len(items)} fresh")
    return items


# ---------- SEC EDGAR 8-K filings ----------
# Regulatory filings for material corporate events - mandatory and immediate
def fetch_sec_8k() -> list[dict]:
    url = (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        "?action=getcompany&type=8-K&dateb=&owner=include&count=40&output=atom"
    )
    try:
        feed = feedparser.parse(
            url,
            request_headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"},
        )
    except Exception as e:
        print(f"[sec] error: {e}")
        return []

    items = []
    cutoff = _cutoff()
    for entry in feed.entries:
        published = None
        if entry.get("updated_parsed"):
            published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
        elif entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        if not published or published < cutoff:
            continue
        items.append({
            "id": _hid("sec", entry.get("id", entry.link)),
            "headline": f"[SEC 8-K] {entry.title}",
            "summary": (entry.get("summary") or "")[:600],
            "source": "SEC EDGAR",
            "url": entry.link,
            "published": published.isoformat(),
            "tickers": [],
        })
    print(f"[sec] {len(items)} fresh 8-K filings")
    return items


# ---------- Press release wires + fastest media (BREAKING ONLY) ----------
RSS_FEEDS: list[tuple[str, str]] = [
    # PR Newswire - press releases from listed US companies (real-time)
    ("https://www.prnewswire.com/rss/news-releases-list.rss", "PR Newswire"),
    # GlobeNewswire - press releases from public companies (real-time)
    (
        "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire+-+News+for+Public+Companies",
        "GlobeNewswire",
    ),
    # Business Wire - Berkshire Hathaway's press release wire (real-time)
    ("https://feed.businesswire.com/rss/home/?rss=G1QFDLJxkRJUWGla", "Business Wire"),
    # MarketWatch real-time breaking headlines (NOT "top stories" which is mixed)
    (
        "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
        "MarketWatch RT",
    ),
    # CNBC top news - mostly real-time
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC"),
]


def fetch_rss(url: str, source_name: str) -> list[dict]:
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})
    except Exception as e:
        print(f"[rss:{source_name}] error: {e}")
        return []

    if not feed.entries:
        print(f"[rss:{source_name}] no entries (feed may be down)")
        return []

    items = []
    cutoff = _cutoff()
    for entry in feed.entries[:50]:
        published = None
        for key in ("published_parsed", "updated_parsed"):
            tp = entry.get(key)
            if tp:
                published = datetime(*tp[:6], tzinfo=timezone.utc)
                break
        if not published or published < cutoff:
            continue
        items.append({
            "id": _hid(source_name, entry.get("link", entry.get("id", entry.title))),
            "headline": entry.title,
            "summary": (entry.get("summary") or "")[:600],
            "source": source_name,
            "url": entry.get("link", ""),
            "published": published.isoformat(),
            "tickers": [],
        })
    print(f"[rss:{source_name}] {len(items)} fresh")
    return items


def fetch_all_news() -> list[dict]:
    items: list[dict] = []
    items.extend(fetch_finnhub_general())
    items.extend(fetch_sec_8k())
    for url, name in RSS_FEEDS:
        items.extend(fetch_rss(url, name))
        time.sleep(0.3)

    # Dedupe by URL
    seen_urls = set()
    deduped = []
    for it in items:
        url = (it.get("url") or "").split("?")[0]
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(it)
    return deduped
