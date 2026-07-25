import statistics
from typing import Optional
from app.database import get_db
from app.models import PriceStats


async def get_product_stats(product_id: int) -> PriceStats:
    """Get price stats for a product (across all its links)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT ph.price FROM price_history ph
            JOIN product_links pl ON pl.id = ph.link_id
            WHERE pl.product_id = ? AND ph.status = 'success' AND ph.price IS NOT NULL
            ORDER BY ph.scraped_at DESC
            """,
            (product_id,),
        )
        rows = await cursor.fetchall()
        prices = [row["price"] for row in rows]

        if not prices:
            return PriceStats(
                current_price=None, min_price=None, max_price=None,
                mean_price=None, median_price=None, std_dev=None,
                total_records=0, first_tracked=None, last_updated=None,
            )

        current = prices[0]
        mean = statistics.mean(prices)
        median = statistics.median(prices)
        std_dev = statistics.stdev(prices) if len(prices) > 1 else 0.0

        cursor2 = await db.execute(
            """
            SELECT MIN(ph.scraped_at) as first, MAX(ph.scraped_at) as last
            FROM price_history ph
            JOIN product_links pl ON pl.id = ph.link_id
            WHERE pl.product_id = ? AND ph.status = 'success'
            """,
            (product_id,),
        )
        dates = await cursor2.fetchone()

        return PriceStats(
            current_price=current,
            min_price=min(prices),
            max_price=max(prices),
            mean_price=round(mean, 2),
            median_price=round(median, 2),
            std_dev=round(std_dev, 2),
            total_records=len(prices),
            first_tracked=dates["first"] if dates else None,
            last_updated=dates["last"] if dates else None,
        )
    finally:
        await db.close()


async def get_link_stats(link_id: int) -> PriceStats:
    """Get price stats for a single link."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT price FROM price_history
            WHERE link_id = ? AND status = 'success' AND price IS NOT NULL
            ORDER BY scraped_at DESC
            """,
            (link_id,),
        )
        rows = await cursor.fetchall()
        prices = [row["price"] for row in rows]

        if not prices:
            return PriceStats(
                current_price=None, min_price=None, max_price=None,
                mean_price=None, median_price=None, std_dev=None,
                total_records=0, first_tracked=None, last_updated=None,
            )

        current = prices[0]
        mean = statistics.mean(prices)
        median = statistics.median(prices)
        std_dev = statistics.stdev(prices) if len(prices) > 1 else 0.0

        cursor2 = await db.execute(
            """
            SELECT MIN(scraped_at) as first, MAX(scraped_at) as last
            FROM price_history WHERE link_id = ? AND status = 'success'
            """,
            (link_id,),
        )
        dates = await cursor2.fetchone()

        return PriceStats(
            current_price=current,
            min_price=min(prices),
            max_price=max(prices),
            mean_price=round(mean, 2),
            median_price=round(median, 2),
            std_dev=round(std_dev, 2),
            total_records=len(prices),
            first_tracked=dates["first"] if dates else None,
            last_updated=dates["last"] if dates else None,
        )
    finally:
        await db.close()


async def get_price_history(product_id: int, limit: int = 100):
    """Get price history for a product (across all links)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT ph.price, ph.status, ph.scraped_at, pl.store, pl.url
            FROM price_history ph
            JOIN product_links pl ON pl.id = ph.link_id
            WHERE pl.product_id = ?
            ORDER BY ph.scraped_at DESC LIMIT ?
            """,
            (product_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_link_price_history(link_id: int, limit: int = 100):
    """Get price history for a single link."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT price, status, scraped_at FROM price_history
            WHERE link_id = ?
            ORDER BY scraped_at DESC LIMIT ?
            """,
            (link_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def get_comparison_data():
    """Get current price + stats for all active products."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name FROM products WHERE active = 1"
        )
        products = await cursor.fetchall()
        results = []
        for p in products:
            # Get best (lowest) current price across all links
            cursor2 = await db.execute(
                """
                SELECT ph.price, pl.store FROM price_history ph
                JOIN product_links pl ON pl.id = ph.link_id
                WHERE pl.product_id = ? AND ph.status = 'success' AND ph.price IS NOT NULL
                ORDER BY ph.scraped_at DESC
                """,
                (p["id"],),
            )
            rows = await cursor2.fetchall()

            # Group by store, get latest price per store
            store_prices = {}
            for r in rows:
                if r["store"] not in store_prices:
                    store_prices[r["store"]] = r["price"]

            if store_prices:
                best_price = min(store_prices.values())
                best_store = min(store_prices, key=lambda k: store_prices[k])
            else:
                best_price = None
                best_store = None

            results.append({
                "id": p["id"],
                "name": p["name"],
                "store": best_store or "N/A",
                "current_price": best_price,
                "store_prices": store_prices,
            })
        return results
    finally:
        await db.close()
