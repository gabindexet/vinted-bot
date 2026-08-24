cat > main.py << 'PYEOF'
import asyncio
import logging
import yaml
from pathlib import Path

from Bot.db import init_db
from Bot.discord_bot import build_bot, send_opportunity_embed, send_error
from Bot.vinted_client import VintedClient
from Bot.scanner import Scanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

async def main():
    with open("config/Config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    init_db()

    client = VintedClient(domain=config.get("domain", "www.vinted.fr"))
    bot = build_bot(config)
    bot.vinted_client = client

    async def on_opportunity(watch, item, price, url, result):
        await send_opportunity_embed(
            bot, config["channels"]["alertes_achat"], watch, item, price, url, result
        )

    async def on_error(message):
        await send_error(bot, config["channels"]["erreurs"], message)

    scanner = Scanner(
        client=client,
        poll_interval=config.get("poll_interval_seconds", 45),
        refresh_cycles=config.get("market_price_refresh_cycles", 20),
        on_opportunity=on_opportunity,
        on_error=on_error,
    )

    await asyncio.gather(
        bot.start(config["discord_bot_token"]),
        scanner.run_forever(),
    )

if __name__ == "__main__":
    asyncio.run(main())
PYEOF
  
