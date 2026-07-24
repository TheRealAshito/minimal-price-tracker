import statistics
from typing import Optional
from app.database import get_db
from app.models import PriceStats


async def get_product_stats(product_id: int) -> PriceStats:
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT price FROM price_history
            WHERE product_id = ? AND status = 'success' AND price IS NOT NULL
            ORDER BY scraped_at DESC
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
            SELECT MIN(scraped_at) as first, MAX(scraped_at) as last
            FROM price_history WHERE product_id = ? AND status = 'success'
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


async def get_price_history(product_id: int, limit: int = 100):
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT price, status, scraped_at FROM price_history
            WHERE product_id = ?
            ORDER BY scraped_at DESC LIMIT ?
            """,
            (product_id, limit),
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
            "SELECT id, name, store FROM products WHERE active = 1"
        )
        products = await cursor.fetchall()
        results = []
        for p in products:
            stats = await get_product_stats(p["id"])
            results.append({
                "id": p["id"],
                "name": p["name"],
                "store": p["store"],
                "current_price": stats.current_price,
                "mean_price": stats.mean_price,
                "min_price": stats.min_price,
                "max_price": stats.max_price,
            })
        return results
    finally:
        await db.close()
