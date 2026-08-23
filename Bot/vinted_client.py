from __future__ import annotations

import logging
import random

import requests

log = logging.getLogger("vinted-bot")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
]


class VintedClient:
    """Client pour l'API interne de Vinted (non-officielle)."""

    def __init__(self, domain: str = "www.vinted.fr"):
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
        if params.get("color_ids"):
            query["color_ids"] = ",".join(map(str, params["color_ids"]))
        if params.get("price_to"):
            query["price_to"] = params["price_to"]

        resp = self.session.get(url, params=query, timeout=15)

        if resp.status_code in (401, 403):
            log.warning("Session Vinted expirée, nouveau warmup...")
            self._warmed_up = False
            self._warmup()
            resp = self.session.get(url, params=query, timeout=15)

        resp.raise_for_status()
        return resp.json().get("items", [])

    def get_item(self, item_id: str) -> dict | None:
        """Récupère un article précis (utilisé par !pricing check <url>)."""
        if not self._warmed_up:
            self._warmup()
        url = f"{self.base_url}/api/v2/items/{item_id}"
        resp = self.session.get(url, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("item")


def item_price(item: dict) -> float | None:
    price = item.get("price") or item.get("total_item_price")
    if not price:
        return None
    try:
        return float(price.get("amount"))
    except (TypeError, ValueError):
        return None


def extract_item_id(url_or_id: str) -> str:
    """Accepte soit un ID brut, soit une URL Vinted du type
    https://www.vinted.fr/items/1234567-titre-annonce"""
    url_or_id = url_or_id.strip()
    if url_or_id.isdigit():
        return url_or_id
    # cherche /items/<digits>
    import re
    m = re.search(r"/items/(\d+)", url_or_id)
    if m:
        return m.group(1)
    return url_or_id
