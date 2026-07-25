import aiosqlite
from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    alert_price_abs REAL,
    alert_price_pct REAL,
    alert_below_mean INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    store TEXT NOT NULL CHECK(store IN ('kabum', 'shopee', 'amazon', 'aliexpress')),
    consecutive_failures INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_product_links_url ON product_links(url);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL,
    price REAL,
    status TEXT NOT NULL CHECK(status IN ('success', 'failed', 'blocked')),
    error_message TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (link_id) REFERENCES product_links(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_history_link ON price_history(link_id);
CREATE INDEX IF NOT EXISTS idx_price_history_scraped ON price_history(scraped_at);
CREATE INDEX IF NOT EXISTS idx_product_links_product ON product_links(product_id);
"""

# Migration SQL for old schema → new schema
MIGRATION_V2 = """
-- Create new tables
CREATE TABLE IF NOT EXISTS product_links_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    store TEXT NOT NULL,
    consecutive_failures INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS price_history_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id INTEGER NOT NULL,
    price REAL,
    status TEXT NOT NULL,
    error_message TEXT,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (link_id) REFERENCES product_links_new(id) ON DELETE CASCADE
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def _table_exists(db, table_name: str) -> bool:
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    row = await cursor.fetchone()
    return row is not None


async def _column_exists(db, table_name: str, column_name: str) -> bool:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    cols = await cursor.fetchall()
    return any(c[1] == column_name for c in cols)


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        # Check if we need migration (old schema has 'url' and 'store' in products table)
        needs_migration = False
        if await _table_exists(db, "products"):
            if await _column_exists(db, "products", "url"):
                needs_migration = True

        if needs_migration:
            await _migrate_v1_to_v2(db)
        else:
            await db.executescript(SCHEMA)

        # Insert default settings if not present
        defaults = {
            "ntfy_url": "",
            "ntfy_port": "",
            "ntfy_topic": "",
            "scrape_interval_hours": "6",
        }
        for key, value in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )
        await db.commit()


async def _migrate_v1_to_v2(db):
    """Migrate from old schema (products with url/store) to new schema (products + product_links)."""
    import logging
    logger = logging.getLogger("price_tracker.migration")
    logger.info("Migrating database from v1 to v2 schema...")

    # Read old products
    cursor = await db.execute("SELECT * FROM products")
    old_products = await cursor.fetchall()

    # Read old price_history
    cursor2 = await db.execute("SELECT * FROM price_history")
    old_history = await cursor2.fetchall()

    # Build mapping: old_product_id → link_id
    product_id_map = {}  # old_product_id → new product_id
    link_id_map = {}     # old_product_id → new link_id

    # Drop old tables
    await db.execute("DROP TABLE IF EXISTS price_history")
    await db.execute("DROP TABLE IF EXISTS products")

    # Create new schema
    await db.executescript(SCHEMA)

    # Migrate data
    for p in old_products:
        # Check if product name already exists (group products by name)
        cursor3 = await db.execute(
            "SELECT id FROM products WHERE name = ?", (p["name"],)
        )
        existing = await cursor3.fetchone()

        if existing:
            new_product_id = existing["id"]
        else:
            await db.execute(
                "INSERT INTO products (name, alert_price_abs, alert_price_pct, alert_below_mean, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (p["name"], p["alert_price_abs"], p["alert_price_pct"],
                 p["alert_below_mean"], p["active"], p["created_at"]),
            )
            new_product_id = db.execute("SELECT last_insert_rowid()").lastrowid
            # Get it properly
            cursor4 = await db.execute("SELECT MAX(id) as id FROM products")
            new_product_id = (await cursor4.fetchone())["id"]

        product_id_map[p["id"]] = new_product_id

        # Create product_link
        await db.execute(
            "INSERT INTO product_links (product_id, url, store, consecutive_failures, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_product_id, p["url"], p["store"], p["consecutive_failures"], p["created_at"]),
        )
        cursor5 = await db.execute("SELECT MAX(id) as id FROM product_links")
        new_link_id = (await cursor5.fetchone())["id"]
        link_id_map[p["id"]] = new_link_id

    # Migrate price_history
    for h in old_history:
        old_pid = h["product_id"]
        if old_pid in link_id_map:
            await db.execute(
                "INSERT INTO price_history (link_id, price, status, error_message, scraped_at) VALUES (?, ?, ?, ?, ?)",
                (link_id_map[old_pid], h["price"], h["status"], h["error_message"], h["scraped_at"]),
            )

    await db.commit()
    logger.info(f"Migration complete. {len(old_products)} products → {len(product_id_map)} grouped products, {len(link_id_map)} links.")
