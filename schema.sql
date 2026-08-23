-- Watches actives
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    keywords TEXT NOT NULL,           -- JSON array de mots-clés
    category TEXT,
    max_price REAL,
    target_brands TEXT,               -- JSON array
    sizes TEXT,                       -- JSON array
    colors TEXT,                      -- JSON array
    condition_min TEXT,               -- JSON array de status_ids
    target_rotation_days INTEGER DEFAULT 10,
    min_margin_pct REAL DEFAULT 120,
    is_active BOOLEAN DEFAULT 1,
    season TEXT DEFAULT 'all',
    alert_channel TEXT,               -- salon Discord dédié (ex: "nike", "carhartt"), sinon fallback
    market_price REAL,                -- prix médian mis en cache
    market_price_updated_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Opportunités détectées
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER REFERENCES watches(id),
    vinted_item_id TEXT UNIQUE,
    title TEXT,
    price REAL,
    market_price REAL,
    estimated_margin_pct REAL,
    score INTEGER,
    recommendation TEXT,              -- 'ACHETER' ou 'PASSER'
    url TEXT,
    detected_at TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'new'         -- 'new', 'notified', 'bought', 'passed'
);

-- Articles en stock / en vente (F5, prêt pour plus tard)
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    brand TEXT,
    category TEXT,
    size TEXT,
    color TEXT,
    condition TEXT,
    purchase_price REAL,
    target_sell_price REAL,
    actual_sell_price REAL,
    status TEXT DEFAULT 'stock',      -- 'stock', 'listed', 'sold', 'shipped'
    source TEXT,                      -- 'manual', 'bot', 'wholesale'
    purchase_date TEXT,
    list_date TEXT,
    sell_date TEXT,
    photos TEXT,                      -- JSON array
    notes TEXT
);

-- Ventes (F5/F9, prêt pour plus tard)
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER REFERENCES items(id),
    sell_price REAL,
    fees REAL,
    shipping_cost REAL,
    net_profit REAL,
    sale_date TEXT DEFAULT (datetime('now'))
);

-- Stats journalières
CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT PRIMARY KEY,
    revenue REAL DEFAULT 0,
    profit REAL DEFAULT 0,
    items_sold INTEGER DEFAULT 0,
    items_listed INTEGER DEFAULT 0,
    opportunities_found INTEGER DEFAULT 0
);

-- Réglages clé/valeur (!config set min-margin 120, etc.)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
