import aiosqlite
import logging
from app.config import DB_PATH

logger = logging.getLogger("price_tracker.database")

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
    store TEXT NOT NULL CHECK(store IN ('kabum', 'shopee', 'amazon', 'aliexpress', 'terabyte', 'generic')),
    custom_selector TEXT,
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
    # PRAGMA doesn't support parameterized queries; validate identifier instead
    assert table_name.replace("_", "").isalnum(), f"Invalid table name: {table_name}"
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    cols = await cursor.fetchall()
    return any(c[1] == column_name for c in cols)


async def _get_check_constraint(db, table_name: str, column_name: str) -> str:
    """Get the current CHECK constraint for a column."""
    cursor = await db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    row = await cursor.fetchone()
    if row:
        sql = row[0]
        # Extract CHECK constraint
        import re
        match = re.search(rf'{column_name}\s+\w+\s+CHECK\(([^)]+)\)', sql, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(DB_PATH)) as db:
        # Check if we need v1→v2 migration (old schema has 'url' in products table)
        needs_v1_migration = False
        if await _table_exists(db, "products"):
            if await _column_exists(db, "products", "url"):
                needs_v1_migration = True

        if needs_v1_migration:
            await _migrate_v1_to_v2(db)
        else:
            # Check if we need v2→v3 migration (add terabyte to CHECK)
            needs_v3_migration = False
            if await _table_exists(db, "product_links"):
                check = await _get_check_constraint(db, "product_links", "store")
                if "terabyte" not in check:
                    needs_v3_migration = True

            if needs_v3_migration:
                await _migrate_v2_to_v3(db)
            else:
                # Check if we need v3→v4 migration (add generic to CHECK + custom_selector column)
                needs_v4_migration = False
                if await _table_exists(db, "product_links"):
                    check = await _get_check_constraint(db, "product_links", "store")
                    if "generic" not in check:
                        needs_v4_migration = True

                if needs_v4_migration:
                    await _migrate_v3_to_v4(db)
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
    logger.info("Migrating database from v1 to v2 schema...")

    cursor = await db.execute("SELECT * FROM products")
    old_products = await cursor.fetchall()

    cursor2 = await db.execute("SELECT * FROM price_history")
    old_history = await cursor2.fetchall()

    product_id_map = {}
    link_id_map = {}

    await db.execute("DROP TABLE IF EXISTS price_history")
    await db.execute("DROP TABLE IF EXISTS products")
    await db.executescript(SCHEMA)

    for p in old_products:
        cursor3 = await db.execute("SELECT id FROM products WHERE name = ?", (p["name"],))
        existing = await cursor3.fetchone()

        if existing:
            new_product_id = existing["id"]
        else:
            await db.execute(
                "INSERT INTO products (name, alert_price_abs, alert_price_pct, alert_below_mean, active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (p["name"], p["alert_price_abs"], p["alert_price_pct"],
                 p["alert_below_mean"], p["active"], p["created_at"]),
            )
            cursor4 = await db.execute("SELECT MAX(id) as id FROM products")
            new_product_id = (await cursor4.fetchone())["id"]

        product_id_map[p["id"]] = new_product_id

        await db.execute(
            "INSERT INTO product_links (product_id, url, store, consecutive_failures, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_product_id, p["url"], p["store"], p["consecutive_failures"], p["created_at"]),
        )
        cursor5 = await db.execute("SELECT MAX(id) as id FROM product_links")
        new_link_id = (await cursor5.fetchone())["id"]
        link_id_map[p["id"]] = new_link_id

    for h in old_history:
        old_pid = h["product_id"]
        if old_pid in link_id_map:
            await db.execute(
                "INSERT INTO price_history (link_id, price, status, error_message, scraped_at) VALUES (?, ?, ?, ?, ?)",
                (link_id_map[old_pid], h["price"], h["status"], h["error_message"], h["scraped_at"]),
            )

    await db.commit()
    logger.info(f"Migration v1→v2 complete. {len(old_products)} products → {len(product_id_map)} grouped products, {len(link_id_map)} links.")


async def _migrate_v2_to_v3(db):
    """Migrate from v2 (4 stores) to v3 (5 stores, adds terabyte)."""
    logger.info("Migrating database from v2 to v3 schema (adding terabyte store)...")

    # SQLite doesn't support ALTER TABLE to modify CHECK constraints.
    # We need to recreate the table.
    # First, read all existing data
    cursor = await db.execute("SELECT * FROM products")
    products = await cursor.fetchall()

    cursor2 = await db.execute("SELECT * FROM product_links")
    links = await cursor2.fetchall()

    cursor3 = await db.execute("SELECT * FROM price_history")
    history = await cursor3.fetchall()

    cursor4 = await db.execute("SELECT key, value FROM settings")
    settings = await cursor4.fetchall()

    # Drop old tables
    await db.execute("DROP TABLE IF EXISTS price_history")
    await db.execute("DROP TABLE IF EXISTS product_links")
    await db.execute("DROP TABLE IF EXISTS products")
    await db.execute("DROP TABLE IF EXISTS settings")

    # Create new schema with updated CHECK
    await db.executescript(SCHEMA)

    # Restore data
    for p in products:
        await db.execute(
            "INSERT INTO products (id, name, alert_price_abs, alert_price_pct, alert_below_mean, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p[0], p[1], p[2], p[3], p[4], p[5], p[6]),
        )

    for l in links:
        await db.execute(
            "INSERT INTO product_links (id, product_id, url, store, consecutive_failures, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (l[0], l[1], l[2], l[3], l[4], l[5]),
        )

    for h in history:
        await db.execute(
            "INSERT INTO price_history (id, link_id, price, status, error_message, scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
            (h[0], h[1], h[2], h[3], h[4], h[5]),
        )

    for s in settings:
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (s[0], s[1]),
        )

    await db.commit()
    logger.info(f"Migration v2→v3 complete. {len(products)} products, {len(links)} links, {len(history)} price records preserved.")


async def _migrate_v3_to_v4(db):
    """Migrate from v3 (5 stores) to v4 (6 stores + custom_selector)."""
    logger.info("Migrating database from v3 to v4 schema (adding generic store + custom_selector)...")

    # Read all existing data
    cursor = await db.execute("SELECT * FROM products")
    products = await cursor.fetchall()

    cursor2 = await db.execute("SELECT * FROM product_links")
    links = await cursor2.fetchall()

    cursor3 = await db.execute("SELECT * FROM price_history")
    history = await cursor3.fetchall()

    cursor4 = await db.execute("SELECT key, value FROM settings")
    settings = await cursor4.fetchall()

    # Drop old tables
    await db.execute("DROP TABLE IF EXISTS price_history")
    await db.execute("DROP TABLE IF EXISTS product_links")
    await db.execute("DROP TABLE IF EXISTS products")
    await db.execute("DROP TABLE IF EXISTS settings")

    # Create new schema with updated CHECK + custom_selector
    await db.executescript(SCHEMA)

    # Restore data
    for p in products:
        await db.execute(
            "INSERT INTO products (id, name, alert_price_abs, alert_price_pct, alert_below_mean, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p[0], p[1], p[2], p[3], p[4], p[5], p[6]),
        )

    for l in links:
        # Old schema: id, product_id, url, store, consecutive_failures, created_at
        # New schema: id, product_id, url, store, custom_selector, consecutive_failures, created_at
        await db.execute(
            "INSERT INTO product_links (id, product_id, url, store, custom_selector, consecutive_failures, created_at) VALUES (?, ?, ?, ?, NULL, ?, ?)",
            (l[0], l[1], l[2], l[3], l[4], l[5]),
        )

    for h in history:
        await db.execute(
            "INSERT INTO price_history (id, link_id, price, status, error_message, scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
            (h[0], h[1], h[2], h[3], h[4], h[5]),
        )

    for s in settings:
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (s[0], s[1]),
        )

    await db.commit()
    logger.info(f"Migration v3→v4 complete. {len(products)} products, {len(links)} links, {len(history)} price records preserved. custom_selector added.")
