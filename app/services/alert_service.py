import logging
from app.database import get_db
from app.services.price_service import get_product_stats

logger = logging.getLogger("price_tracker.alerts")


async def evaluate_alerts(product_id: int, link_id: int, current_price: float):
    """Check if any alert thresholds are triggered for a product."""
    if current_price is None:
        return

    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        product = await cursor.fetchone()
        if not product:
            return

        # Get the link URL for the alert message
        cursor_link = await db.execute("SELECT url FROM product_links WHERE id = ?", (link_id,))
        link = await cursor_link.fetchone()
        link_url = link["url"] if link else ""

        stats = await get_product_stats(product_id)

        # Absolute price alert
        if product["alert_price_abs"] and current_price <= product["alert_price_abs"]:
            logger.info(f"Price alert: {product['name']} at R$ {current_price:,.2f} (absolute threshold R$ {product['alert_price_abs']:,.2f}) link={link_url}")

        # Percentage drop alert (from first tracked price)
        if product["alert_price_pct"] and stats.max_price:
            initial_price = stats.max_price
            if initial_price and initial_price > 0:
                drop_pct = ((initial_price - current_price) / initial_price) * 100
                if drop_pct >= product["alert_price_pct"]:
                    logger.info(f"Price alert: {product['name']} at R$ {current_price:,.2f} ({drop_pct:.1f}% drop) link={link_url}")

        # Below mean alert
        if product["alert_below_mean"] and stats.mean_price:
            if current_price < stats.mean_price:
                logger.info(f"Price alert: {product['name']} at R$ {current_price:,.2f} (below mean R$ {stats.mean_price:,.2f}) link={link_url}")
    finally:
        await db.close()


async def handle_scrape_failure(link_id: int):
    """Increment failure count, log warnings, auto-disable if needed."""
    from app.config import settings

    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT pl.id, pl.consecutive_failures, pl.url, pl.store, p.name, p.id as product_id
            FROM product_links pl
            JOIN products p ON p.id = pl.product_id
            WHERE pl.id = ?
            """,
            (link_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return

        new_count = (row["consecutive_failures"] or 0) + 1

        # Log warning at threshold
        if new_count == settings.alert_failure_threshold:
            logger.warning(f"Scrape failure: {row['name']} failed {new_count} consecutive times ({row['url']})")

        # Auto-disable after max failures
        if new_count >= settings.max_consecutive_failures:
            await db.execute(
                "UPDATE product_links SET consecutive_failures = ? WHERE id = ?",
                (new_count, link_id),
            )
            # Also disable the parent product
            await db.execute(
                "UPDATE products SET active = 0 WHERE id = ?",
                (row["product_id"],),
            )
            logger.warning(f"Scrape failure: {row['name']} auto-disabled after {new_count} failures ({row['url']})")
        else:
            await db.execute(
                "UPDATE product_links SET consecutive_failures = ? WHERE id = ?",
                (new_count, link_id),
            )
        await db.commit()
    finally:
        await db.close()


async def reset_failures(link_id: int):
    """Reset failure count on successful scrape."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE product_links SET consecutive_failures = 0 WHERE id = ?",
            (link_id,),
        )
        await db.commit()
    finally:
        await db.close()
