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


async def get_best_deal(product_id: int) -> Optional[dict]:
    """
    Find the best current deal for a product across all its links.
    Returns dict with store, url, price, savings vs worst, savings vs mean.
    """
    db = await get_db()
    try:
        # Get latest price for each link
        cursor = await db.execute("""
            SELECT pl.id, pl.store, pl.url, ph.price, ph.scraped_at
            FROM product_links pl
            JOIN (
                SELECT link_id, price, scraped_at,
                       ROW_NUMBER() OVER (PARTITION BY link_id ORDER BY scraped_at DESC) as rn
                FROM price_history
                WHERE status = 'success' AND price IS NOT NULL
            ) ph ON ph.link_id = pl.id AND ph.rn = 1
            WHERE pl.product_id = ?
            ORDER BY ph.price ASC
        """, (product_id,))
        rows = await cursor.fetchall()

        if not rows or len(rows) < 1:
            return None

        deals = [dict(row) for row in rows]
        best = deals[0]
        worst = deals[-1] if len(deals) > 1 else best

        # Calculate savings
        savings_vs_worst = worst["price"] - best["price"] if len(deals) > 1 else 0
        savings_pct = (savings_vs_worst / worst["price"] * 100) if worst["price"] > 0 else 0

        # Get historical mean for context
        cursor2 = await db.execute("""
            SELECT AVG(ph.price) as mean_price
            FROM price_history ph
            JOIN product_links pl ON pl.id = ph.link_id
            WHERE pl.product_id = ? AND ph.status = 'success' AND ph.price IS NOT NULL
        """, (product_id,))
        mean_row = await cursor2.fetchone()
        mean_price = mean_row["mean_price"] if mean_row else None

        savings_vs_mean = (mean_price - best["price"]) if mean_price else 0
        savings_vs_mean_pct = (savings_vs_mean / mean_price * 100) if mean_price and mean_price > 0 else 0

        return {
            "best_store": best["store"],
            "best_url": best["url"],
            "best_price": best["price"],
            "best_scraped_at": best["scraped_at"],
            "worst_store": worst["store"],
            "worst_price": worst["price"],
            "savings_vs_worst": round(savings_vs_worst, 2),
            "savings_vs_worst_pct": round(savings_pct, 1),
            "mean_price": round(mean_price, 2) if mean_price else None,
            "savings_vs_mean": round(savings_vs_mean, 2),
            "savings_vs_mean_pct": round(savings_vs_mean_pct, 1),
            "all_deals": deals,
        }
    finally:
        await db.close()


async def get_comparison_data():
    """Get current price + best deal for all active products."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name FROM products WHERE active = 1"
        )
        products = await cursor.fetchall()
        results = []
        for p in products:
            deal = await get_best_deal(p["id"])
            if deal:
                results.append({
                    "id": p["id"],
                    "name": p["name"],
                    "store": deal["best_store"],
                    "current_price": deal["best_price"],
                    "store_prices": {d["store"]: d["price"] for d in deal["all_deals"]},
                    "savings_vs_worst": deal["savings_vs_worst"],
                    "savings_vs_worst_pct": deal["savings_vs_worst_pct"],
                })
        return results
    finally:
        await db.close()
