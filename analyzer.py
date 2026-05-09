# Skopiuj do .env i wypełnij. NIE commituj .env do repo!

# Klucz Claude API - https://console.anthropic.com -> Settings -> API Keys
ANTHROPIC_API_KEY=sk-ant-...

# Finnhub - darmowy token: https://finnhub.io/register
FINNHUB_TOKEN=

# Telegram bot token - utwórz przez @BotFather na Telegramie
TELEGRAM_BOT_TOKEN=

# Twoje chat ID - napisz cokolwiek do swojego bota, potem otwórz:
# https://api.telegram.org/bot<TOKEN>/getUpdates  i znajdź "chat":{"id": NUMBER}
TELEGRAM_CHAT_ID=

# Próg pilności (1-10). 6 = umiarkowany, 7-8 = tylko duże, 9+ = tylko sensacje.
URGENCY_THRESHOLD=6

# Ile godzin wstecz patrzeć przy każdym uruchomieniu (cutoff dla starych newsów).
MAX_AGE_HOURS=2

# Model Claude do scoringu (haiku = tani i szybki; sonnet = lepszy ale 5x droższy)
CLAUDE_MODEL=claude-haiku-4-5
