from app.database import get_db
from app.services.price_service import get_product_stats
from app.services.ntfy_service import send_price_alert, send_failure_alert


async def evaluate_alerts(product_id: int, current_price: float):
    """Check if any alert thresholds are triggered for a product."""
    if current_price is None:
        return

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        )
        product = await cursor.fetchone()
        if not product:
            return

        stats = await get_product_stats(product_id)

        # Absolute price alert
        if product["alert_price_abs"] and current_price <= product["alert_price_abs"]:
            await send_price_alert(
                product["name"], current_price,
                "Absolute threshold", product["alert_price_abs"],
                product["url"],
            )

        # Percentage drop alert (from first tracked price)
        if product["alert_price_pct"] and stats.min_price:
            initial_price = stats.max_price  # earliest = highest in DESC order
            if initial_price and initial_price > 0:
                drop_pct = ((initial_price - current_price) / initial_price) * 100
                if drop_pct >= product["alert_price_pct"]:
                    await send_price_alert(
                        product["name"], current_price,
                        f"Percentage drop ({drop_pct:.1f}%)", product["alert_price_pct"],
                        product["url"],
                    )

        # Below mean alert
        if product["alert_below_mean"] and stats.mean_price:
            if current_price < stats.mean_price:
                await send_price_alert(
                    product["name"], current_price,
                    "Below historical mean", stats.mean_price,
                    product["url"],
                )
    finally:
        await db.close()


async def handle_scrape_failure(product_id: int):
    """Increment failure count, send alerts, auto-disable if needed."""
    from app.config import settings

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT consecutive_failures, name, url FROM products WHERE id = ?",
            (product_id,),
        )
        product = await cursor.fetchone()
        if not product:
            return

        new_count = product["consecutive_failures"] + 1

        # Send NTFY alert at threshold
        if new_count == settings.alert_failure_threshold:
            await send_failure_alert(product["name"], new_count, product["url"])

        # Auto-disable after max failures
        if new_count >= settings.max_consecutive_failures:
            await db.execute(
                "UPDATE products SET active = 0, consecutive_failures = ? WHERE id = ?",
                (new_count, product_id),
            )
            await send_failure_alert(product["name"], new_count, product["url"])
        else:
            await db.execute(
                "UPDATE products SET consecutive_failures = ? WHERE id = ?",
                (new_count, product_id),
            )
        await db.commit()
    finally:
        await db.close()


async def reset_failures(product_id: int):
    """Reset failure count on successful scrape."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE products SET consecutive_failures = 0 WHERE id = ?",
            (product_id,),
        )
        await db.commit()
    finally:
        await db.close()
