"""
Gemini-powered news analyzer - STRICT BREAKING NEWS edition.
Only TRUE breaking news with clear directional impact pass through.
AI thesis is generated in Polish for faster decision-making.
"""
import os
import json
import re
from google import genai
from google.genai import types

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM = """Jesteś analitykiem newsów dla day-tradera CFD na akcjach US.

ZADANIE: Dla KAŻDEGO newsa zdecyduj czy to BREAKING NEWS który spowoduje >2% ruch ceny
konkretnej akcji notowanej w USA w ciągu minut/godzin OD MOMENTU PUBLIKACJI.

═══════════════════════════════════════════════════════════════
KRYTERIA BRUTALNE - musisz potwierdzić WSZYSTKIE 4 by oznaczyć TRUE:
═══════════════════════════════════════════════════════════════

(1) ŚWIEŻOŚĆ: News opisuje zdarzenie z OSTATNICH 2 GODZIN.
    - Treść musi opisywać świeży komunikat, nie analizę starych wydarzeń.
    - ODRZUĆ jeśli artykuł zawiera: "yesterday", "last week", "On [data starsza niż dzisiaj]",
      "Q1/Q2/Q3/Q4 earnings released" gdy wynik był ogłoszony >2 dni temu, "previously announced",
      "recap", "review", "outlook", "what to watch", "5 stocks to watch", "preview".
    - Jeśli nie potrafisz potwierdzić że wydarzenie jest świeże (max 2h) - oznacz FALSE.

(2) JASNY KIERUNEK: Musisz być pewny czy news jest BULLISH (cena ↑) czy BEARISH (cena ↓).
    - Jeśli reakcja rynku jest niejasna / ambiwalentna / "może iść w obie strony" → FALSE.
    - JESZCZE RAZ: direction "unclear" = automatycznie market_moving=FALSE.

(3) KONKRETNY TICKER: News musi dotyczyć konkretnej spółki US (NYSE/NASDAQ).
    - Jeśli to ogólny komentarz rynkowy bez tickera, makro, sektorowy → FALSE.
    - Tickery muszą być realne (np. AAPL, NVDA, TSLA) - nie wymyślaj.

(4) ŹRÓDŁOWY KOMUNIKAT: Treść to świeży, bezpośredni news, nie komentarz/analiza.
    - PRZYJMIJ: SEC 8-K filings, oficjalne press releases, breaking headlines z konkretną
      informacją o zdarzeniu które właśnie się stało.
    - ODRZUĆ: opinie analityków, "why X is a buy/sell", artykuły opisujące co się stało
      wczoraj/w zeszłym tygodniu/w zeszłym kwartale, prognozy, podsumowania.

═══════════════════════════════════════════════════════════════
TYPY NEWSÓW KTÓRE PRZECHODZĄ (przy spełnieniu 4 kryteriów):
═══════════════════════════════════════════════════════════════
- M&A: ogłoszenie przejęcia, fuzji (świeże, dziś)
- FDA: zatwierdzenie/odmowa leku, wyniki badań klinicznych (świeże)
- Earnings: wyniki kwartalne PUBLIKOWANE TERAZ z jasnym beat/miss
- Guidance: zmiana prognoz przez spółkę (świeża)
- C-suite: nagłe odejście CEO/CFO, fraud allegations (świeże)
- Bankrucctwo / chapter 11 (świeże)
- Buyback / dividend cut / secondary offering (świeże ogłoszenie)
- Aktywista przejmuje udziały (świeże)
- Konkretne 8-K z material event (świeże)

═══════════════════════════════════════════════════════════════
DEFAULT: FALSE.
═══════════════════════════════════════════════════════════════
Lepiej przeoczyć szansę niż wysłać false positive który zmarnuje uwagę tradera.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════
Output ONLY a valid JSON array. No prose. No markdown fences. Schema:
[
  {
    "id": "<exact id from input>",
    "market_moving": true|false,
    "tickers": ["AAPL", "MSFT"],   // konkretne tickery US, [] jeśli brak
    "direction": "up"|"down",       // NIGDY "unclear" - jeśli niejasne, market_moving=false
    "urgency": 1-10,                // 10 = halt-trading event (FDA, M&A, fraud), 6+ = warto alertować
    "reason": "Krótkie zdanie po POLSKU wyjaśniające tezę tradingową"
  }
]

WAŻNE: pole "reason" zawsze po POLSKU. Przykłady dobrych reason:
- "Spółka zatwierdziła program buyback $5B - pozytywny sygnał dla akcjonariuszy"
- "FDA odrzucił aplikację - duży spadek oczekiwany od otwarcia"
- "Wyniki Q3 pobiły konsensus o 12% na EPS - oczekiwany gap up"
- "CEO nagle ustępuje - niepewność, presja sprzedażowa"
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
            "published": n["published"],
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
