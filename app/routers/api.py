from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.database import get_db
from app.services.price_service import get_product_stats, get_price_history, get_comparison_data, get_link_stats

router = APIRouter(prefix="/api")


@router.get("/products/{product_id}/prices")
async def api_price_history(product_id: int, limit: int = 100):
    history = await get_price_history(product_id, limit)
    return JSONResponse(history)


@router.get("/products/{product_id}/stats")
async def api_product_stats(product_id: int):
    stats = await get_product_stats(product_id)
    return JSONResponse(stats.model_dump())


@router.get("/links/{link_id}/stats")
async def api_link_stats(link_id: int):
    stats = await get_link_stats(link_id)
    return JSONResponse(stats.model_dump())


@router.get("/comparison")
async def api_comparison():
    data = await get_comparison_data()
    return JSONResponse(data)


@router.get("/dashboard/summary")
async def api_dashboard_summary():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as c FROM products WHERE active = 1")
        active = (await cursor.fetchone())["c"]

        cursor2 = await db.execute("SELECT COUNT(*) as c FROM product_links WHERE consecutive_failures > 0")
        failing = (await cursor2.fetchone())["c"]

        cursor3 = await db.execute("""
            SELECT COUNT(DISTINCT link_id) as c FROM price_history
            WHERE status = 'success' AND scraped_at > datetime('now', '-24 hours')
        """)
        scraped_today = (await cursor3.fetchone())["c"]

    finally:
        await db.close()

    return JSONResponse({
        "active_products": active,
        "failing_links": failing,
        "scraped_last_24h": scraped_today,
    })
