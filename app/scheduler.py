import asyncio
import logging
import random
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database import get_db
from app.scrapers.registry import get_scraper
from app.services.alert_service import evaluate_alerts, handle_scrape_failure, reset_failures
from app.services.backup_service import prune_old_data

logger = logging.getLogger("price_tracker.scheduler")
scheduler = AsyncIOScheduler()


async def scrape_product(product_id: int, url: str, store: str, name: str):
    """Scrape a single product and record the result."""
    scraper = get_scraper(store)
    try:
        # Random delay to avoid pattern detection
        await asyncio.sleep(random.uniform(2, 8))

        price, error = await scraper.scrape(url)

        db = await get_db()
        try:
            if price is not None:
                await db.execute(
                    "INSERT INTO price_history (product_id, price, status) VALUES (?, ?, 'success')",
                    (product_id, price),
                )
                await db.commit()
                await reset_failures(product_id)
                await evaluate_alerts(product_id, price)
                logger.info(f"Scraped {name}: R$ {price:,.2f}")
            else:
                await db.execute(
                    "INSERT INTO price_history (product_id, status, error_message) VALUES (?, 'failed', ?)",
                    (product_id, error),
                )
                await db.commit()
                await handle_scrape_failure(product_id)
                logger.warning(f"Failed to scrape {name}: {error}")
        finally:
            await db.close()
    except Exception as e:
        logger.error(f"Error scraping {name}: {e}")
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO price_history (product_id, status, error_message) VALUES (?, 'failed', ?)",
                (product_id, str(e)[:500]),
            )
            await db.commit()
            await handle_scrape_failure(product_id)
        finally:
            await db.close()
    finally:
        await scraper.close()


async def run_all_scrapes():
    """Scrape all active products sequentially with delays."""
    logger.info("Starting scheduled scrape run...")
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name, url, store FROM products WHERE active = 1"
        )
        products = await cursor.fetchall()
    finally:
        await db.close()

    if not products:
        logger.info("No active products to scrape.")
        return

    for p in products:
        await scrape_product(p["id"], p["url"], p["store"], p["name"])

    logger.info(f"Scrape run complete. Processed {len(products)} products.")

    # Prune old data after each run
    await prune_old_data()


async def run_single_product(product_id: int):
    """Scrape a single product immediately."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name, url, store FROM products WHERE id = ?", (product_id,)
        )
        product = await cursor.fetchone()
        if product:
            await scrape_product(product["id"], product["url"], product["store"], product["name"])
    finally:
        await db.close()


def start_scheduler(interval_hours: int = 6):
    """Start the APScheduler with the given interval."""
    scheduler.add_job(
        run_all_scrapes,
        "interval",
        hours=interval_hours,
        id="price_scrape",
        replace_existing=True,
        next_run_time=datetime.now(),  # Run immediately on startup
    )
    scheduler.start()
    logger.info(f"Scheduler started. Scraping every {interval_hours} hours.")


def stop_scheduler():
    scheduler.shutdown()
