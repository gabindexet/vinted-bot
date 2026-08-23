#!/usr/bin/env python3
"""
Bot Vinted -> Discord
Surveille des recherches Vinted, calcule le prix médian du marché pour
chacune, et envoie sur Discord les annonces dont le prix est nettement
en dessous de ce médian (= bon plan).
"""
from __future__ import annotations
import json
import logging
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import requests
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("vinted-bot")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "vinted_bot.db"
CONFIG_PATH = BASE_DIR / "config.yaml"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
]


class VintedClient:
    """Petit client pour l'API interne de Vinted (non-officielle)."""

    def __init__(self, domain: str):
        self.domain = domain
        self.base_url = f"https://{domain}"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fr-FR,fr;q=0.9",
            }
        )
        self._warmed_up = False

    def _warmup(self):
        """Récupère les cookies de session nécessaires pour l'API."""
        resp = self.session.get(self.base_url + "/", timeout=15)
        resp.raise_for_status()
        self._warmed_up = True

    def search(self, params: dict, per_page: int = 40) -> list[dict]:
        if not self._warmed_up:
            self._warmup()

        url = f"{self.base_url}/api/v2/catalog/items"
        query = {
            "per_page": per_page,
            "page": 1,
            "search_text": params.get("search_text", ""),
            "order": params.get("order", "newest_first"),
        }
        if params.get("catalog_ids"):
            query["catalog_ids"] = ",".join(map(str, params["catalog_ids"]))
        if params.get("brand_ids"):
            query["brand_ids"] = ",".join(map(str, params["brand_ids"]))
        if params.get("size_ids"):
            query["size_ids"] = ",".join(map(str, params["size_ids"]))
        if params.get("status_ids"):
            query["status_ids"] = ",".join(map(str, params["status_ids"]))
        if params.get("price_to"):
            query["price_to"] = params["price_to"]

        resp = self.session.get(url, params=query, timeout=15)

        # Si Vinted renvoie 401/403, la session a expiré -> on refait un warmup
        if resp.status_code in (401, 403):
            log.warning("Session expirée, nouveau warmup...")
            self._warmed_up = False
            self._warmup()
            resp = self.session.get(url, params=query, timeout=15)

        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.error("config.yaml introuvable à côté du script.")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_items (
            item_id INTEGER PRIMARY KEY,
            watch_name TEXT,
            seen_at INTEGER
        )
        """
    )
    conn.commit()
    return conn


def already_seen(conn, item_id: int) -> bool:
    cur = conn.execute("SELECT 1 FROM seen_items WHERE item_id = ?", (item_id,))
    return cur.fetchone() is not None


def mark_seen(conn, item_id: int, watch_name: str):
    conn.execute(
        "INSERT OR IGNORE INTO seen_items (item_id, watch_name, seen_at) VALUES (?, ?, ?)",
        (item_id, watch_name, int(time.time())),
    )
    conn.commit()


def item_price(item: dict) -> float | None:
    price = item.get("price") or item.get("total_item_price")
    if not price:
        return None
    try:
        return float(price.get("amount"))
    except (TypeError, ValueError):
        return None


def compute_market_price(client: VintedClient, watch: dict) -> float | None:
    """Prix médian sur un échantillon large trié par pertinence (pas newest)."""
    params = dict(watch)
    params["order"] = "relevance"
    items = client.search(params, per_page=96)
    prices = [p for p in (item_price(i) for i in items) if p is not None]
    if len(prices) < 5:
        return None
    # On coupe les 10% extrêmes de chaque côté pour éviter que des annonces
    # aberrantes (lots, pièces détachées, erreurs de prix) faussent le calcul.
    prices.sort()
    trim = max(1, len(prices) // 10)
    trimmed = prices[trim:-trim] if len(prices) > 2 * trim else prices
    return statistics.median(trimmed)


def send_discord_alert(webhook_url: str, watch_name: str, item: dict, market_price: float):
    price = item_price(item)
    discount_pct = round((1 - price / market_price) * 100)
    photo = (item.get("photo") or {}).get("url")
    item_url = f"https://www.vinted.fr/items/{item['id']}"

    embed = {
        "title": item.get("title", "Annonce Vinted"),
        "url": item_url,
        "color": 0x1DBF73,
        "fields": [
            {"name": "Prix", "value": f"{price:.2f} €", "inline": True},
            {"name": "Prix médian marché", "value": f"{market_price:.2f} €", "inline": True},
            {"name": "Réduction estimée", "value": f"-{discount_pct}%", "inline": True},
            {"name": "Recherche", "value": watch_name, "inline": False},
        ],
    }
    if photo:
        embed["thumbnail"] = {"url": photo}

    payload = {
        "content": f"🔥 Bon plan repéré sur **{watch_name}**",
        "embeds": [embed],
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code >= 300:
            log.warning("Discord a répondu %s: %s", resp.status_code, resp.text[:200])
    except requests.RequestException as e:
        log.warning("Échec envoi Discord: %s", e)


def analyze_niche(client: VintedClient, seed: str, discount_threshold: float,
                   status_ids: list) -> dict | None:
    """Échantillonne une recherche large et estime son potentiel de bons plans."""
    params = {"search_text": seed, "order": "relevance", "status_ids": status_ids}
    items = client.search(params, per_page=96)
    prices = [p for p in (item_price(i) for i in items) if p is not None]
    if len(prices) < 10:
        return None

    prices.sort()
    trim = max(1, len(prices) // 10)
    trimmed = prices[trim:-trim] if len(prices) > 2 * trim else prices
    median_price = statistics.median(trimmed)

    deal_count = sum(1 for p in prices if p <= median_price * (1 - discount_threshold))
    deal_ratio = deal_count / len(prices)

    return {
        "seed": seed,
        "sample_size": len(prices),
        "median_price": round(median_price, 2),
        "deal_ratio": round(deal_ratio, 3),
    }


def run_niche_discovery(client: VintedClient, webhook_url: str, seeds: list,
                         discount_threshold: float, status_ids: list, top_n: int):
    log.info("Lancement de la découverte de niches (%d recherches)...", len(seeds))
    results = []
    for seed in seeds:
        try:
            r = analyze_niche(client, seed, discount_threshold, status_ids)
            if r:
                results.append(r)
                log.info("[niche] %s: médian=%.2f€ ratio_deals=%.1f%% (n=%d)",
                          r["seed"], r["median_price"], r["deal_ratio"] * 100, r["sample_size"])
        except requests.RequestException as e:
            log.warning("[niche] erreur sur '%s': %s", seed, e)
        time.sleep(random.uniform(2, 5))

    if not results:
        return

    results.sort(key=lambda r: r["deal_ratio"], reverse=True)
    top = results[:top_n]

    lines = [
        f"**{r['seed']}** — {r['deal_ratio']*100:.1f}% de bons plans "
        f"potentiels · médian {r['median_price']:.2f} € (n={r['sample_size']})"
        for r in top
    ]
    payload = {
        "content": "📊 **Rapport de découverte de niches**\n" + "\n".join(lines) +
                   "\n\n_Indicateur basé sur un échantillon, pas une garantie de "
                   "rentabilité. Ajoute les meilleures dans `watches` si ça t'intéresse._",
    }
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except requests.RequestException as e:
        log.warning("Échec envoi rapport niches: %s", e)


def run():
    config = load_config()
    webhook_url = config["discord_webhook"]
    domain = config.get("domain", "www.vinted.fr")
    poll_interval = config.get("poll_interval_seconds", 180)
    refresh_cycles = config.get("market_price_refresh_cycles", 20)
    discount_threshold = config.get("discount_threshold", 0.30)
    watches = config.get("watches", [])

    if not watches:
        log.error("Aucune recherche définie dans config.yaml (clé 'watches').")
        sys.exit(1)

    # Applique le filtre d'état par défaut à chaque watch qui n'en définit pas
    default_status_ids = config.get("status_ids")
    if default_status_ids:
        for watch in watches:
            watch.setdefault("status_ids", default_status_ids)

    discovery_cfg = config.get("niche_discovery", {})
    discovery_enabled = discovery_cfg.get("enabled", False)
    discovery_interval = discovery_cfg.get("interval_hours", 6) * 3600
    discovery_top_n = discovery_cfg.get("top_n_report", 5)
    discovery_seeds = discovery_cfg.get("seeds", [])
    last_discovery = 0.0

    client = VintedClient(domain)
    conn = init_db()

    market_prices = {}
    cycle = 0

    log.info("Bot démarré. %d recherche(s) surveillée(s). Intervalle: %ds",
              len(watches), poll_interval)

    while True:
        cycle += 1

        if discovery_enabled and discovery_seeds and \
                (time.time() - last_discovery) >= discovery_interval:
            try:
                run_niche_discovery(client, webhook_url, discovery_seeds,
                                     discount_threshold, config.get("status_ids", []),
                                     discovery_top_n)
            except Exception as e:
                log.exception("Erreur pendant la découverte de niches: %s", e)
            last_discovery = time.time()

        for watch in watches:
            name = watch["name"]
            try:
                # Recalcule le prix marché au 1er cycle et périodiquement
                if name not in market_prices or cycle % refresh_cycles == 0:
                    mp = compute_market_price(client, watch)
                    if mp:
                        market_prices[name] = mp
                        log.info("[%s] prix médian marché: %.2f €", name, mp)
                    elif name not in market_prices:
                        log.warning("[%s] pas assez de données pour estimer le marché, "
                                    "réessai au prochain cycle.", name)
                        continue

                market_price = market_prices.get(name)
                if not market_price:
                    continue

                items = client.search(watch, per_page=20)  # newest_first par défaut
                for item in items:
                    item_id = item.get("id")
                    if item_id is None or already_seen(conn, item_id):
                        continue

                    price = item_price(item)
                    if price is None:
                        mark_seen(conn, item_id, name)
                        continue

                    mark_seen(conn, item_id, name)

                    if watch.get("max_price") and price > watch["max_price"]:
                        continue

                    discount = 1 - (price / market_price)
                    if discount >= discount_threshold:
                        log.info("[%s] BON PLAN: %s à %.2f € (-%.0f%%)",
                                  name, item.get("title"), price, discount * 100)
                        send_discord_alert(webhook_url, name, item, market_price)

            except requests.RequestException as e:
                log.warning("[%s] erreur réseau: %s", name, e)
            except Exception as e:
                log.exception("[%s] erreur inattendue: %s", name, e)

            # petite pause entre chaque recherche pour rester discret
            time.sleep(random.uniform(2, 5))

        time.sleep(poll_interval)


if __name__ == "__main__":
    run()
