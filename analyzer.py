"""
Claude-powered news analyzer.
Sends a batch of news items to Claude, gets back per-item market-impact scores.
Uses Haiku 4.5 by default - fast and cheap, plenty good for headline classification.
"""
import os
import json
import re
from anthropic import Anthropic

_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")

SYSTEM = """You are a financial news triage analyst for a short-term CFD trader.

Your job: for EACH news item, decide if it is likely to cause a >2% short-term price move
in any US-listed stock (NYSE/NASDAQ) within minutes to hours.

What counts as market-moving (mark TRUE):
  - M&A announcements (acquirer or target)
  - FDA approvals/rejections, clinical trial results, recalls
  - Earnings results that surprise vs consensus, guidance changes, preannouncements
  - Lawsuits/SEC actions/government investigations on a specific company
  - CEO/CFO sudden departures, fraud allegations
  - Major contracts, partnerships, large customer wins/losses
  - Bankruptcy, going-concern warnings, dividend cuts/suspensions
  - Activist investor stakes, share buybacks, secondary offerings
  - Sector-wide regulatory shocks naming specific companies
  - Material 8-K filings (when content is specific)

What is NOT market-moving (mark FALSE):
  - General market commentary, opinion, "what to watch" pieces
  - Earnings PREVIEWS or reminders without new info
  - Analyst price-target tweaks (unless dramatic)
  - Old news being recycled
  - Macro takes without specific tickers
  - Crypto/forex/commodity-only news (we trade equities)
  - Generic corporate filings, routine 8-Ks (executive comp updates, bylaw changes)

Output ONLY a valid JSON array. No prose, no markdown fences. Schema:
[
  {
    "id": "<exact id from input>",
    "market_moving": true|false,
    "tickers": ["AAPL", "MSFT"],   // US tickers only; [] if unclear or not a stock
    "direction": "up"|"down"|"unclear",
    "urgency": 1-10,                // 10 = halt-the-stock level (FDA decision, M&A, fraud)
    "reason": "one short sentence explaining the trade thesis"
  },
  ...
]

Be strict. If unsure, set market_moving=false. False positives waste the trader's attention.
"""


def _parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    # Strip markdown fences if Claude added them despite instructions
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Find the first [ and last ] if there's prose around
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def analyze_news(items: list[dict]) -> list[dict]:
    """Returns items annotated with: market_moving, tickers, direction, urgency, reason."""
    if not items:
        return []

    payload = [
        {
            "id": n["id"],
            "headline": n["headline"],
            "summary": n["summary"][:400],
            "source": n["source"],
            "ticker_hints": n.get("tickers", []),
        }
        for n in items
    ]

    user_msg = "Analyze these news items:\n\n" + json.dumps(payload, ensure_ascii=False)

    try:
        resp = _client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = resp.content[0].text
        scores = _parse_json_array(text)
    except Exception as e:
        print(f"[analyzer] error: {e}")
        return items  # nothing flagged -> nothing sent

    by_id = {s.get("id"): s for s in scores if isinstance(s, dict)}

    out = []
    for item in items:
        score = by_id.get(item["id"], {})
        out.append({**item, **score})
    return out
