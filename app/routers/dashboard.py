from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.services.price_service import get_product_stats, get_comparison_data

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = await get_db()
    try:
        # Get summary stats
        cursor = await db.execute("SELECT COUNT(*) as total FROM products WHERE active = 1")
        total_active = (await cursor.fetchone())["total"]

        cursor = await db.execute("SELECT COUNT(*) as total FROM products")
        total_products = (await cursor.fetchone())["total"]

        cursor = await db.execute(
            "SELECT COUNT(*) as total FROM products WHERE consecutive_failures > 0"
        )
        failing = (await cursor.fetchone())["total"]

        # Get recent price changes
        cursor = await db.execute("""
            SELECT p.name, p.store, ph.price, ph.scraped_at, p.id
            FROM price_history ph
            JOIN products p ON p.id = ph.product_id
            WHERE ph.status = 'success'
            ORDER BY ph.scraped_at DESC LIMIT 10
        """)
        recent_prices = [dict(row) for row in await cursor.fetchall()]

        # Get comparison data for charts
        comparison = await get_comparison_data()

    finally:
        await db.close()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "total_active": total_active,
        "total_products": total_products,
        "failing": failing,
        "recent_prices": recent_prices,
        "comparison": comparison,
    })
