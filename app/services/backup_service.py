import csv
import io
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from app.database import get_db
from app.config import DB_PATH, settings


async def export_backup() -> Path:
    """Create a backup copy of the database and return its path."""
    backup_dir = Path("data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"price_tracker_backup_{timestamp}.db"
    shutil.copy2(str(DB_PATH), str(backup_path))
    return backup_path


async def restore_backup(source_path: str):
    """Restore database from a backup file."""
    source = Path(source_path)
    if not source.exists():
        raise FileNotFoundError(f"Backup not found: {source_path}")
    shutil.copy2(str(source), str(DB_PATH))


async def export_product_csv(product_id: int) -> io.StringIO:
    """Export a product's price history as CSV."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT name FROM products WHERE id = ?", (product_id,)
        )
        product = await cursor.fetchone()
        if not product:
            raise ValueError("Product not found")

        cursor2 = await db.execute(
            """
            SELECT pl.store, pl.url, ph.price, ph.status, ph.scraped_at
            FROM price_history ph
            JOIN product_links pl ON pl.id = ph.link_id
            WHERE pl.product_id = ?
            ORDER BY ph.scraped_at ASC
            """,
            (product_id,),
        )
        rows = await cursor2.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["product_name", "store", "url", "price_brl", "status", "scraped_at"])
        for row in rows:
            writer.writerow([
                product["name"], row["store"], row["url"],
                row["price"], row["status"], row["scraped_at"],
            ])
        output.seek(0)
        return output
    finally:
        await db.close()


async def prune_old_data():
    """Delete price history older than max_history_days."""
    cutoff = datetime.now() - timedelta(days=settings.max_history_days)
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM price_history WHERE scraped_at < ?",
            (cutoff.isoformat(),),
        )
        await db.commit()
    finally:
        await db.close()
