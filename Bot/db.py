from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


# ── Watches ───────────────────────────────────────────────────────────

def add_watch(
    name: str,
    keywords: list[str],
    max_price: float | None = None,
    category: str | None = None,
    target_brands: list[str] | None = None,
    sizes: list[str] | None = None,
    colors: list[str] | None = None,
    condition_min: list[int] | None = None,
    target_rotation_days: int = 10,
    min_margin_pct: float = 120,
    alert_channel: str | None = None,
) -> int:
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO watches
            (name, keywords, max_price, category, target_brands, sizes,
             colors, condition_min, target_rotation_days, min_margin_pct,
             alert_channel)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            json.dumps(keywords),
            max_price,
            category,
            json.dumps(target_brands or []),
            json.dumps(sizes or []),
            json.dumps(colors or []),
            json.dumps(condition_min or []),
            target_rotation_days,
            min_margin_pct,
            alert_channel,
        ),
    )
    conn.commit()
    watch_id = cur.lastrowid
    conn.close()
    return watch_id


def list_watches(active_only: bool = False) -> list[sqlite3.Row]:
    conn = get_conn()
    q = "SELECT * FROM watches"
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY id"
    rows = conn.execute(q).fetchall()
    conn.close()
    return rows


def get_watch(watch_id: int) -> sqlite3.Row | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM watches WHERE id = ?", (watch_id,)).fetchone()
    conn.close()
    return row


def remove_watch(watch_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM watches WHERE id = ?", (watch_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def set_watch_active(watch_id: int, active: bool) -> bool:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE watches SET is_active = ? WHERE id = ?", (int(active), watch_id)
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def update_market_price(watch_id: int, market_price: float):
    conn = get_conn()
    conn.execute(
        "UPDATE watches SET market_price = ?, market_price_updated_at = ? WHERE id = ?",
        (market_price, datetime.utcnow().isoformat(), watch_id),
    )
    conn.commit()
    conn.close()


# ── Opportunités ──────────────────────────────────────────────────────

def opportunity_exists(vinted_item_id: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM opportunities WHERE vinted_item_id = ?", (vinted_item_id,)
    ).fetchone()
    conn.close()
    return row is not None


def log_opportunity(
    watch_id: int,
    vinted_item_id: str,
    title: str,
    price: float,
    market_price: float,
    estimated_margin_pct: float,
    score: int,
    recommendation: str,
    url: str,
):
    conn = get_conn()
    conn.execute(
        """
        INSERT OR IGNORE INTO opportunities
            (watch_id, vinted_item_id, title, price, market_price,
             estimated_margin_pct, score, recommendation, url, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'notified')
        """,
        (watch_id, vinted_item_id, title, price, market_price,
         estimated_margin_pct, score, recommendation, url),
    )
    conn.commit()
    bump_daily_stat("opportunities_found", 1)
    conn.close()


# ── Stats journalières ────────────────────────────────────────────────

def bump_daily_stat(field: str, amount: float):
    today = date.today().isoformat()
    conn = get_conn()
    conn.execute(
        "INSERT INTO daily_stats (date) VALUES (?) ON CONFLICT(date) DO NOTHING",
        (today,),
    )
    conn.execute(
        f"UPDATE daily_stats SET {field} = {field} + ? WHERE date = ?",
        (amount, today),
    )
    conn.commit()
    conn.close()


def get_stats_range(days: int) -> list[sqlite3.Row]:
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM daily_stats WHERE date >= ? ORDER BY date", (since,)
    ).fetchall()
    conn.close()
    return rows


# ── Réglages ──────────────────────────────────────────────────────────

def set_setting(key: str, value: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_setting(key: str, default: str | None = None) -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default
