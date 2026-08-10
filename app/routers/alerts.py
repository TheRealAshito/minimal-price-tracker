from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.database import get_db

router = APIRouter(prefix="/alerts")
from app.templates_config import templates


@router.get("", response_class=HTMLResponse)
async def alerts_page(request: Request):
    db = await get_db()
    try:
        # Get recent price alerts (drops below thresholds)
        cursor = await db.execute("""
            SELECT p.name, pl.store, pl.url, p.alert_price_abs, p.alert_price_pct,
                   p.alert_below_mean, ph.price, ph.scraped_at
            FROM price_history ph
            JOIN product_links pl ON pl.id = ph.link_id
            JOIN products p ON p.id = pl.product_id
            WHERE ph.status = 'success'
            AND (
                (p.alert_price_abs IS NOT NULL AND ph.price <= p.alert_price_abs)
                OR (p.alert_below_mean = 1)
            )
            ORDER BY ph.scraped_at DESC
            LIMIT 50
        """)
        triggered = [dict(row) for row in await cursor.fetchall()]

        # Get links with failures
        cursor2 = await db.execute("""
            SELECT p.name, pl.store, pl.url, pl.consecutive_failures, p.active
            FROM product_links pl
            JOIN products p ON p.id = pl.product_id
            WHERE pl.consecutive_failures > 0
            ORDER BY pl.consecutive_failures DESC
        """)
        failures = [dict(row) for row in await cursor2.fetchall()]

    finally:
        await db.close()

    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "triggered": triggered,
        "failures": failures,
    })
