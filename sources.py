# Market News Monitor 📈

Monitor newsów giełdowych dla US stocks. Co 10 minut pobiera newsy z wielu źródeł, ocenia
przez Claude API które z nich mogą krótkoterminowo ruszyć ceną konkretnej spółki, i wysyła
alert na Telegram. Działa w GitHub Actions (darmowo, 24/7) — alerty przychodzą jak push na
telefon z Telegrama.

## Co dostajesz w alercie

```
🟢 ↑  $TSLA  |  Urgency: 8/10 🔥🔥🔥🔥🔥🔥🔥🔥

Tesla Reports Q3 Deliveries Beat by 8%, Margins Expand

💡 Beat consensus by ~8% on deliveries with margin expansion;
   typical 5-10% gap up on similar prior surprises.

📰 MarketWatch  |  otwórz
🕐 2026-05-09T18:23:00+00:00
```

## Co potrzebujesz (wszystko darmowe poza Claude API)

1. **Konto GitHub** — bezpłatne
2. **Klucz Claude API** — https://console.anthropic.com → Settings → API Keys
   - Koszt: szacunkowo $5–15/miesiąc przy modelu Haiku (default), 144 uruchomień dziennie
3. **Finnhub token** — https://finnhub.io/register, 60 req/min za darmo
4. **Bot Telegrama** — utwórz przez `@BotFather`, weź token, napisz cokolwiek do bota,
   otwórz `https://api.telegram.org/bot<TOKEN>/getUpdates` żeby znaleźć swoje `chat_id`

## Setup (15 minut)

### 1. Stwórz repo na GitHub

```bash
# w folderze z plikami:
git init
git add .
git commit -m "init"
gh repo create news-monitor --private --source=. --push
# albo zrób ręcznie: stwórz repo na github.com i wypchaj
```

**Repo MUSI być prywatne** (Twoje sekrety nie powinny wisieć publicznie, no i klucze API
mimo że są w GitHub Secrets).

### 2. Dodaj sekrety w GitHub

W repo: `Settings → Secrets and variables → Actions → New repository secret`. Dodaj:

| Nazwa sekretu | Wartość |
|---|---|
| `ANTHROPIC_API_KEY` | sk-ant-... |
| `FINNHUB_TOKEN` | Twój Finnhub token |
| `TELEGRAM_BOT_TOKEN` | token od @BotFather |
| `TELEGRAM_CHAT_ID` | Twoje chat ID (liczba, możliwe że ujemna) |

Opcjonalnie zmień próg pilności w `Settings → Variables → Actions`:
- `URGENCY_THRESHOLD` (zmienna, nie sekret) = `6` (default), `7` lub `8`

### 3. Włącz workflow

W repo: zakładka `Actions` → włącz workflows jeśli zapyta → uruchom ręcznie pierwszy raz
(`News Monitor → Run workflow`) żeby sprawdzić czy działa.

Patrz w logi — jeśli widzisz np. `[finnhub] 35 fresh items` i `[telegram] sent: ...`, działa.

Po pierwszym ręcznym uruchomieniu, scheduler sam zacznie odpalać co 10 minut.

## Lokalny test (opcjonalny)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # i wypełnij
export $(cat .env | xargs)
python monitor.py
```

## Strojenie

**Za dużo alertów?** Podnieś `URGENCY_THRESHOLD` do 7 lub 8.

**Za mało alertów / pomija newsy?** Obniż threshold do 5, lub zmień model w
`monitor.yml` na `claude-sonnet-4-6` (wyższa precyzja, ale ~5x droższy).

**Chcesz inne źródła?** Edytuj `RSS_FEEDS` w `sources.py`. Możliwości:
- Benzinga (płatne API, ale bardzo szybkie alerty traderskie)
- Twitter/X (trudne — API kosztuje, scraping zablokowany)
- Reddit r/wallstreetbets (`https://www.reddit.com/r/wallstreetbets/.json`)
- Konkretne tickery z Finnhub: `/api/v1/company-news?symbol=AAPL&from=...&to=...`

**Chcesz inny ton/styl analizy?** Edytuj prompt `SYSTEM` w `analyzer.py`.

**Chcesz tylko określone tickery / sektory?** Dodaj filtr po `analyze_news` w `monitor.py`,
np. `if not any(t in WATCHLIST for t in item["tickers"]): continue`.

## Architektura

```
GitHub Actions (cron */10 * * * *)
        ↓
    monitor.py
        ├── sources.py  ──→ Finnhub API + SEC EDGAR + RSS feeds
        ├── state.py    ──→ state.json (jakie newsy już widziałem)
        ├── analyzer.py ──→ Claude API (czy news ruszy ceną, jaki ticker)
        └── notifier.py ──→ Telegram Bot API → push na telefon
```

## Ważne zastrzeżenia

- **GitHub Actions cron jest "best effort"** — w praktyce uruchomienia mogą być opóźnione
  o 1–15 min w godzinach szczytu. Jeśli potrzebujesz absolutnej punktualności,
  rozważ Cloudflare Workers Cron Triggers (działa co do sekundy).
- **Żaden filtr AI nie jest 100% trafny.** Claude czasami przepuści szum lub przeoczy
  realny news. Zawsze waliduj przed kliknięciem buy/sell.
- **Najszybsze newsy są płatne.** Bloomberg/Refinitiv/Benzinga Pro wyprzedzają darmowe
  źródła o sekundy/minuty. Ten setup to "good enough free tier".
- **Nie jest to porada inwestycyjna.** Trading na newsach na CFD to handel z dźwignią —
  wiesz co robisz na własną odpowiedzialność.

## Koszty (orientacyjnie)

- GitHub Actions: **$0** (darmowy tier obejmuje 2000 min/mies dla repo prywatnego — Ty
  zużyjesz ~30s × 144 = 72 min/dzień = ~2160 min/mies, czyli mieścisz się w cuglach;
  *publiczne repo* ma nielimitowane minutes ale wtedy uważaj na sekrety)
- Finnhub: **$0** (free tier wystarczy)
- Telegram: **$0**
- Claude API (Haiku): **~$5–15/mies** (zależy od liczby pobranych newsów; ~25 newsów × 144 runs/dzień)
- Total: **~$5–15/mies**
