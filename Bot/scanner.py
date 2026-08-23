from __future__ import annotations

import asyncio
import json
import logging
import random
import statistics
import time

from . import db, pricing
from .vinted_client import VintedClient, item_price

log = logging.getLogger("vinted-bot")


def _watch_to_search_params(watch) -> dict:
    keywords = json.loads(watch["keywords"])
    return {
        "search_text": " ".join(keywords),
        "brand_ids": json.loads(watch["target_brands"] or "[]"),
        "size_ids": json.loads(watch["sizes"] or "[]"),
        "color_ids": json.loads(watch["colors"] or "[]"),
        "status_ids": json.loads(watch["condition_min"] or "[]"),
    }


def compute_market_price(client: VintedClient, params: dict) -> float | None:
    p = dict(params)
    p["order"] = "relevance"
    items = client.search(p, per_page=96)
    prices = [pr for pr in (item_price(i) for i in items) if pr is not None]
    if len(prices) < 5:
        return None
    prices.sort()
    trim = max(1, len(prices) // 10)
    trimmed = prices[trim:-trim] if len(prices) > 2 * trim else prices
    return statistics.median(trimmed)


class Scanner:
    """Boucle de scan F1+F2. Appelle `on_opportunity(watch, item, pricing_result)`
    et `on_error(message)` — branchés au bot Discord dans main.py."""

    def __init__(self, client: VintedClient, poll_interval: int,
                 refresh_cycles: int, on_opportunity, on_error):
        self.client = client
        self.poll_interval = poll_interval
        self.refresh_cycles = refresh_cycles
        self.on_opportunity = on_opportunity
        self.on_error = on_error
        self._cycle = 0
        self._running = False

    async def run_forever(self):
        self._running = True
        log.info("Scanner démarré (intervalle: %ds)", self.poll_interval)
        while self._running:
            self._cycle += 1
            watches = db.list_watches(active_only=True)
            for watch in watches:
                try:
                    await self._scan_watch(watch)
                except Exception as e:
                    log.exception("Erreur scan watch %s: %s", watch["name"], e)
                    await self.on_error(f"Erreur sur la watch **{watch['name']}** : `{e}`")
                await asyncio.sleep(random.uniform(1.5, 3.5))
            await asyncio.sleep(self.poll_interval)

    def stop(self):
        self._running = False

    async def _scan_watch(self, watch):
        params = _watch_to_search_params(watch)

        # Rafraîchit le prix marché périodiquement (calcul bloquant -> executor)
        loop = asyncio.get_running_loop()
        if watch["market_price"] is None or self._cycle % self.refresh_cycles == 0:
            mp = await loop.run_in_executor(None, compute_market_price, self.client, params)
            if mp:
                db.update_market_price(watch["id"], mp)
                watch = db.get_watch(watch["id"])
                log.info("[%s] prix médian marché: %.2f €", watch["name"], mp)

        market_price = watch["market_price"]
        if not market_price:
            return

        newest_params = dict(params)
        if watch["max_price"]:
            newest_params["price_to"] = watch["max_price"]
        items = await loop.run_in_executor(
            None, self.client.search, newest_params, 20
        )

        for item in items:
            item_id = str(item.get("id"))
            if not item_id or db.opportunity_exists(item_id):
                continue

            price = item_price(item)
            if price is None:
                continue

            result = pricing.compute_rentability(
                prix_achat=price,
                prix_median_marche=market_price,
                rotation_days=watch["target_rotation_days"],
                min_margin_pct=watch["min_margin_pct"],
            )

            item_url = f"{self.client.base_url}/items/{item_id}"
            db.log_opportunity(
                watch_id=watch["id"],
                vinted_item_id=item_id,
                title=item.get("title", "Article Vinted"),
                price=price,
                market_price=market_price,
                estimated_margin_pct=result["marge_brute_pct"],
                score=result["score"],
                recommendation=result["recommendation"],
                url=item_url,
            )

            if result["recommendation"] == "ACHETER":
                log.info("[%s] ACHETER: %s à %.2f€ (score %d)",
                          watch["name"], item.get("title"), price, result["score"])
                await self.on_opportunity(watch, item, price, item_url, result)
      
