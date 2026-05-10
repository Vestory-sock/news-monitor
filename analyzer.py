"""
Gemini-powered news analyzer (replaces Anthropic Claude version).
Sends a batch of news items to Gemini, gets back per-item market-impact scores.
Uses Gemini 2.5 Flash by default - free tier, plenty good for headline classification.
"""
import os
import json
import re
from google import genai
from google.genai import types

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
    "tickers": ["AAPL", "MSFT"],
    "direction": "up"|"down"|"unclear",
    "urgency": 1-10,
    "reason": "one short sentence explaining the trade thesis"
  }
]

Be strict. If unsure, set market_moving=false. False positives waste the trader's attention.
"""


def _parse_json_array(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
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
        resp = _client.models.generate_content(
            model=MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                temperature=0.0,
                max_output_tokens=8192,
                response_mime_type="application/json",
            ),
        )
        text = resp.text
        scores = _parse_json_array(text)
    except Exception as e:
        print(f"[analyzer] error: {e}")
        return items

    by_id = {s.get("id"): s for s in scores if isinstance(s, dict)}

    out = []
    for item in items:
        score = by_id.get(item["id"], {})
        out.append({**item, **score})
    return out
