import httpx
from app.database import get_db


async def get_ntfy_settings() -> dict:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT key, value FROM settings WHERE key IN ('ntfy_url', 'ntfy_port', 'ntfy_topic')"
        )
        rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        await db.close()


async def send_ntfy(title: str, message: str, tags: str = "price_tag"):
    cfg = await get_ntfy_settings()
    url = cfg.get("ntfy_url", "").strip()
    port = cfg.get("ntfy_port", "").strip()
    topic = cfg.get("ntfy_topic", "").strip()

    if not all([url, topic]):
        return  # NTFY not configured

    # Build endpoint
    base = url.rstrip("/")
    if port:
        base = f"{base}:{port}"
    endpoint = f"{base}/{topic}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                endpoint,
                content=message,
                headers={
                    "Title": title,
                    "Tags": tags,
                    "Content-Type": "text/plain; charset=utf-8",
                },
            )
    except Exception as e:
        import logging
        logging.getLogger("price_tracker.ntfy").warning(f"NTFY notification failed: {e}")


async def send_price_alert(product_name: str, current_price: float,
                           trigger_type: str, threshold: float, url: str):
    title = f"💰 Price Alert: {product_name}"
    message = (
        f"Price: R$ {current_price:,.2f}\n"
        f"Trigger: {trigger_type}\n"
        f"Threshold: R$ {threshold:,.2f}\n"
        f"Link: {url}"
    )
    await send_ntfy(title, message, tags="money_with_wings,cart")


async def send_failure_alert(product_name: str, consecutive: int, url: str):
    title = f"⚠️ Scrape Failure: {product_name}"
    message = (
        f"Failed {consecutive} consecutive times.\n"
        f"URL: {url}\n"
        f"{'Product will be auto-disabled after 10 failures.' if consecutive < 10 else 'Product has been auto-disabled.'}"
    )
    await send_ntfy(title, message, tags="warning")


async def send_weekly_summary(products_data: list):
    if not products_data:
        return
    lines = ["Weekly Price Summary:\n"]
    for p in products_data:
        change = ""
        if p.get("current_price") and p.get("mean_price"):
            diff = ((p["current_price"] - p["mean_price"]) / p["mean_price"]) * 100
            change = f" ({'+' if diff > 0 else ''}{diff:.1f}% vs avg)"
        lines.append(f"• {p['name']}: R$ {p.get('current_price', 'N/A'):,.2f}{change}")
    await send_ntfy("📊 Weekly Summary", "\n".join(lines), tags="chart_with_upwards_trend")
