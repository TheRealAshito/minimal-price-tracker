import asyncio
import logging
import random
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database import get_db
from app.scrapers.registry import get_scraper
from app.services.alert_service import evaluate_alerts, handle_scrape_failure, reset_failures
from app.services.backup_service import prune_old_data

logger = logging.getLogger("price_tracker.scheduler")
scheduler = AsyncIOScheduler()


async def scrape_link(link_id: int, url: str, store: str, product_id: int, product_name: str, custom_selector: Optional[str] = None):
    """Scrape a single product link and record the result."""
    scraper = get_scraper(store)
    try:
        # Random delay to avoid pattern detection
        await asyncio.sleep(random.uniform(2, 8))

        price, error = await scraper.scrape(url, custom_selector=custom_selector)

        db = await get_db()
        try:
            if price is not None:
                await db.execute(
                    "INSERT INTO price_history (link_id, price, status) VALUES (?, ?, 'success')",
                    (link_id, price),
                )
                await db.commit()
                await reset_failures(link_id)
                await evaluate_alerts(product_id, link_id, price)
                logger.info(f"Scraped {product_name} ({store}): R$ {price:,.2f}")
            else:
                await db.execute(
                    "INSERT INTO price_history (link_id, status, error_message) VALUES (?, 'failed', ?)",
                    (link_id, error),
                )
                await db.commit()
                await handle_scrape_failure(link_id)
                logger.warning(f"Failed to scrape {product_name} ({store}): {error}")
        finally:
            await db.close()
    except Exception as e:
        logger.error(f"Error scraping {product_name} ({store}): {e}")
        db = await get_db()
        try:
            await db.execute(
                "INSERT INTO price_history (link_id, status, error_message) VALUES (?, 'failed', ?)",
                (link_id, str(e)[:500]),
            )
            await db.commit()
            await handle_scrape_failure(link_id)
        finally:
            await db.close()
    finally:
        await scraper.close()


async def run_all_scrapes():
    """Scrape all active product links sequentially with delays."""
    logger.info("Starting scheduled scrape run...")
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT pl.id, pl.url, pl.store, pl.custom_selector, p.id as product_id, p.name
            FROM product_links pl
            JOIN products p ON p.id = pl.product_id
            WHERE p.active = 1
        """)
        links = await cursor.fetchall()
    finally:
        await db.close()

    if not links:
        logger.info("No active product links to scrape.")
        return

    for link in links:
        await scrape_link(link["id"], link["url"], link["store"], link["product_id"], link["name"],
                         custom_selector=link["custom_selector"])

    logger.info(f"Scrape run complete. Processed {len(links)} links.")

    # Prune old data after each run
    await prune_old_data()


async def run_single_product(product_id: int):
    """Scrape all links for a single product immediately."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT pl.id, pl.url, pl.store, pl.custom_selector, p.name
            FROM product_links pl
            JOIN products p ON p.id = pl.product_id
            WHERE pl.product_id = ?
        """, (product_id,))
        links = await cursor.fetchall()

        for link in links:
            await scrape_link(link["id"], link["url"], link["store"], product_id, link["name"],
                             custom_selector=link["custom_selector"])
    finally:
        await db.close()


async def run_single_link(link_id: int):
    """Scrape a single link immediately."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT pl.id, pl.url, pl.store, pl.custom_selector, pl.product_id, p.name
            FROM product_links pl
            JOIN products p ON p.id = pl.product_id
            WHERE pl.id = ?
        """, (link_id,))
        link = await cursor.fetchone()
        if link:
            await scrape_link(link["id"], link["url"], link["store"], link["product_id"], link["name"],
                             custom_selector=link["custom_selector"])
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
