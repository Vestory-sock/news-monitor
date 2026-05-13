"""
Gemini-powered news analyzer - PHASE 1 QUALITY EDITION.

Filters applied in this layer:
1. Mega-cap filter: $500B+ companies need much stronger news to trigger alerts
2. Recap detection: rejects re-coverage of old events, class action PR, ongoing trials
3. Asian ADR blacklist: hardcoded list of Asian ADRs to skip entirely
4. Paper gains detection: warns when "gains" are unrealized/fair-value (not cash)

AI thesis is generated in Polish for faster decision-making.
"""
import os
import json
import re
from google import genai
from google.genai import types

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ═══════════════════════════════════════════════════════════════
# ASIAN ADR BLACKLIST - skip these entirely
# ═══════════════════════════════════════════════════════════════
ASIAN_ADRS = {
    # Japonia
    "SFTBY", "SFTBF",   # SoftBank
    "TM",                # Toyota
    "HMC",               # Honda
    "SONY",              # Sony
    "NSANY",             # Nissan
    "MUFG",              # Mitsubishi UFJ
    "MFG",               # Mizuho Financial
    "SMFG",              # Sumitomo Mitsui
    "NTDOY",             # Nintendo
    "PCRFY",             # Panasonic
    "MTU",               # Mitsubishi
    "HTHIY",             # Hitachi
    "RNECY",             # Renesas
    "FJTSY",             # Fujitsu
    "TOELY",             # Tokyo Electron
    "SMTOY",             # Sumitomo Metal Mining
    # Chiny / Hong Kong
    "BABA",              # Alibaba
    "JD",                # JD.com
    "PDD",               # Pinduoduo
    "BIDU",              # Baidu
    "NTES",              # NetEase
    "TCEHY", "TCEHF",    # Tencent
    "TCOM",              # Trip.com
    "NIO",               # NIO
    "XPEV",              # XPeng
    "LI",                # Li Auto
    "BILI",              # Bilibili
    "VIPS",              # Vipshop
    "ZTO",               # ZTO Express
    "YMM",               # Full Truck Alliance
    "DIDI", "DIDIY",     # Didi Global
    "BGNE",              # BeiGene
    "LFC",               # China Life Insurance
    "ACH",               # Aluminum Corp of China
    "PNGAY",             # Ping An Insurance
    "CHTRY",             # China Telecom
    "CICHY",             # China Construction Bank
    # Korea
    "SSNLF",             # Samsung
    "LPL",               # LG Display
    "KB",                # KB Financial
    "SHG",               # Shinhan Financial
    "WF",                # Woori Financial
    "PKX",               # POSCO
    # Tajwan
    "TSM",               # TSMC
    "UMC",               # United Microelectronics
    "ASX",               # ASE Technology
    "HIMX",              # Himax Technologies
    # Indie
    "INFY",              # Infosys
    "WIT",               # Wipro
    "HDB",               # HDFC Bank
    "IBN",               # ICICI Bank
    "RDY",               # Dr. Reddy's
    "TTM",               # Tata Motors
    "SLT",               # SLR Investment
}


def is_asian_adr(ticker: str) -> bool:
    """Check if ticker is on the Asian ADR blacklist."""
    if not ticker:
        return False
    return ticker.upper().strip() in ASIAN_ADRS


def filter_asian_adrs(tickers: list[str]) -> tuple[list[str], list[str]]:
    """Split tickers into (kept, rejected_asian). Returns (filtered, blacklisted)."""
    kept = []
    blacklisted = []
    for t in tickers or []:
        if is_asian_adr(t):
            blacklisted.append(t.upper())
        else:
            kept.append(t)
    return kept, blacklisted


# ═══════════════════════════════════════════════════════════════
# PAPER GAINS DETECTION - heuristic for unrealized gains language
# ═══════════════════════════════════════════════════════════════
PAPER_GAINS_PATTERNS = [
    "unrealized gain", "unrealized gains",
    "paper gain", "paper gains",
    "fair value increase", "fair-value increase",
    "fair value gain", "fair-value gain",
    "valuation increase", "valuation gain",
    "mark-to-market", "marked to market",
    "marked up", "revalued",
    "non-cash gain", "non-cash gains",
    "unrealized profit",
]


def has_paper_gains_language(text: str) -> bool:
    """Check if news contains unrealized/paper gains language."""
    if not text:
        return False
    text_lower = text.lower()
    return any(pattern in text_lower for pattern in PAPER_GAINS_PATTERNS)


# ═══════════════════════════════════════════════════════════════
# GEMINI SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════
SYSTEM = """Jesteś elitarnym analitykiem newsów dla day-tradera CFD na akcjach US.
Twoje zadanie: filtrować szum, przepuszczać tylko najlepsze breaking news.

═══════════════════════════════════════════════════════════════
KRYTERIA BRUTALNE - musisz potwierdzić WSZYSTKIE 4 by oznaczyć TRUE:
═══════════════════════════════════════════════════════════════

(1) ŚWIEŻOŚĆ: News opisuje zdarzenie z OSTATNICH 2 GODZIN.
    - Treść musi opisywać świeży komunikat, nie analizę starych wydarzeń.
    - ODRZUĆ jeśli artykuł zawiera: "yesterday", "last week", "On [data starsza niż dzisiaj]",
      "Q1/Q2/Q3/Q4 earnings released" gdy wynik był >2 dni temu, "previously announced",
      "recap", "review", "outlook", "what to watch", "5 stocks to watch", "preview".

(2) JASNY KIERUNEK: Musisz być pewny czy news jest BULLISH (cena ↑) czy BEARISH (cena ↓).
    - Jeśli reakcja rynku jest niejasna / ambiwalentna → market_moving=FALSE.
    - Direction "unclear" = AUTOMATYCZNIE market_moving=FALSE.

(3) KONKRETNY TICKER: News dotyczy konkretnej spółki US (NYSE/NASDAQ).
    - Jeśli to ogólny komentarz rynkowy, makro, sektorowy → FALSE.

(4) ŹRÓDŁOWY KOMUNIKAT: Treść to świeży, bezpośredni news, nie komentarz/analiza.

═══════════════════════════════════════════════════════════════
🔴 BLACKLISTA - AUTOMATYCZNE ODRZUCENIE (market_moving=FALSE):
═══════════════════════════════════════════════════════════════

A) CLASS ACTION / KANCELARIE PRAWNE (marketing, nie news):
   - Headline'y od kancelarii: Berger Montague, Schall Law, Rosen Law, Pomerantz,
     Glancy Prongay, Faruqi & Faruqi, Bronstein Gewirtz, Bragar Eagel, Howard G. Smith,
     Levi & Korsinsky, Robbins Geller, Kessler Topaz, Hagens Berman
   - Frazy: "DEADLINE APPROACHING", "DEADLINE REMINDER", "INVESTOR ALERT",
     "INVESTORS WHO LOST MONEY", "Class Action", "Securities Fraud Class Action",
     "Advises Investors", "On Behalf Of", "Final Deadline", "Lead Plaintiff Deadline"

B) TRWAJĄCE PROCESY / DZIENNIKI Z SĄDU:
   - "trial day X", "X day of testimony", "ongoing lawsuit", "ongoing trial"
   - "in continuing court proceedings", "court hearing", "testimony reveals"
   - "as reported earlier", "as previously disclosed"

C) RECAP / KOMENTARZ / PREVIEW:
   - "Why X is a buy/sell", "5 stocks to watch", "stocks to buy now"
   - "preview", "outlook", "what to expect"
   - Wyniki kwartalne z datą publikacji w treści starszą niż 7 dni

═══════════════════════════════════════════════════════════════
🟡 MEGA-CAP FILTER - PODNIESIONE PROGI:
═══════════════════════════════════════════════════════════════

Dla spółek z market cap >$500B (tj. AAPL, MSFT, NVDA, GOOGL, GOOG, AMZN, META, TSLA,
BRK.A, BRK.B, LLY, JPM, V, MA, WMT, XOM, UNH, HD, COST, PG, JNJ, BAC, ABBV, ORCL):

WYMAGAJ żeby news był MATERIAL EVENT:
- Earnings beat/miss >5%
- Guidance change
- CEO/CFO departure (nagła, nieplanowana)
- Antitrust ruling / major regulatory action
- M&A transaction worth >5% market cap
- Major recall affecting CORE business (nie subsidiary)
- Material accounting issue / fraud allegations

ODRZUĆ DLA MEGA-CAP jeśli:
- News dotyczy subsidiary o marginalnym wkładzie do revenue (np. Waymo dla Alphabet)
- "Voluntary recall" bez NHTSA mandate
- Plotki / niepotwierdzone informacje
- Komentarze CEO / wywiady (bez konkretnej zmiany strategii)
- Pozwy które już istnieją (kolejne dni procesu)
- Drobne aktualizacje produktów, partnerstwa
- News o produkcie wpisującym się w kategorię "code", "Engineering", "experimental"

═══════════════════════════════════════════════════════════════
🟠 PAPER GAINS WARNING:
═══════════════════════════════════════════════════════════════

Jeśli news mówi o "gain" / "profit" / "$X billion" i ZARAZEM zawiera:
- "unrealized", "paper gain", "fair value", "valuation increase", "mark-to-market",
  "non-cash", "marked up", "revalued"

To są KSIĘGOWE zyski, NIE cash. Rynek je dyskontuje.
→ OBNIŻ urgency o 2 punkty (lub odrzuć jeśli to jedyny catalyst).

═══════════════════════════════════════════════════════════════
TYPY NEWSÓW KTÓRE PRZECHODZĄ (przy spełnieniu 4 kryteriów):
═══════════════════════════════════════════════════════════════
- M&A: ogłoszenie przejęcia, fuzji (świeże, dziś)
- FDA: zatwierdzenie/odmowa leku, wyniki badań klinicznych (świeże)
- Earnings: wyniki PUBLIKOWANE TERAZ z jasnym beat/miss
- Guidance: zmiana prognoz przez spółkę (świeża)
- C-suite: nagłe odejście CEO/CFO, fraud allegations (świeże)
- Bankrucctwo / chapter 11 (świeże)
- Buyback / dividend cut / secondary offering (świeże ogłoszenie)
- Aktywista przejmuje udziały (świeże)
- 8-K z material event (świeże)
- Duży kontrakt komercyjny (proporcjonalnie do wielkości spółki!)

═══════════════════════════════════════════════════════════════
DEFAULT: FALSE. Lepiej przeoczyć szansę niż wysłać false positive.
═══════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════
Output ONLY a valid JSON array. No prose. No markdown fences. Schema:
[
  {
    "id": "<exact id from input>",
    "market_moving": true|false,
    "tickers": ["AAPL", "MSFT"],
    "direction": "up"|"down",
    "urgency": 1-10,
    "reason": "Krótkie zdanie po POLSKU wyjaśniające tezę tradingową",
    "is_paper_gains": true|false,
    "rejection_reason": "krótko po polsku jeśli market_moving=false, inaczej null"
  }
]

WAŻNE:
- pole "reason" zawsze po POLSKU
- pole "is_paper_gains" oznaczaj true jeśli zysk jest księgowy (nie cash)
- pole "rejection_reason" wypełnij gdy market_moving=false (np. "class action PR", "mega-cap subsidiary news")
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
    """Returns items annotated with: market_moving, tickers, direction, urgency, reason, is_paper_gains."""
    if not items:
        return []

    # PRE-FILTER: drop items where ALL tickers are Asian ADRs
    pre_filtered = []
    for n in items:
        hints = n.get("tickers") or []
        kept, blacklisted = filter_asian_adrs(hints)
        if hints and not kept:
            # All tickers were Asian ADRs - skip without calling Gemini
            print(f"[analyzer] skip Asian ADR: {n.get('headline','')[:60]} (tickers: {blacklisted})")
            continue
        pre_filtered.append(n)

    if not pre_filtered:
        return []

    payload = [
        {
            "id": n["id"],
            "headline": n["headline"],
            "summary": n["summary"][:400],
            "source": n["source"],
            "published": n["published"],
            "ticker_hints": n.get("tickers", []),
        }
        for n in pre_filtered
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
        return pre_filtered

    by_id = {s.get("id"): s for s in scores if isinstance(s, dict)}

    out = []
    for item in pre_filtered:
        score = by_id.get(item["id"], {})
        merged = {**item, **score}

        # POST-FILTER: remove any Asian ADRs that Gemini may have added back
        if merged.get("tickers"):
            kept, blacklisted = filter_asian_adrs(merged["tickers"])
            if blacklisted and not kept:
                # All resulting tickers are Asian ADRs - reject
                merged["market_moving"] = False
                merged["rejection_reason"] = f"Asian ADR blacklist: {','.join(blacklisted)}"
            elif blacklisted:
                # Some Asian ADRs - just remove them, keep others
                merged["tickers"] = kept

        # ADDITIONAL CHECK: scan content for paper gains language (belt-and-suspenders)
        # If Gemini missed it, we catch it here
        if merged.get("market_moving") and not merged.get("is_paper_gains"):
            combined_text = (item.get("headline","") + " " + item.get("summary",""))
            if has_paper_gains_language(combined_text):
                merged["is_paper_gains"] = True
                # Reduce urgency by 2 for paper gains
                current_urgency = int(merged.get("urgency", 0))
                merged["urgency"] = max(1, current_urgency - 2)

        out.append(merged)
    return out
