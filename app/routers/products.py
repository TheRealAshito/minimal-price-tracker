from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.models import ProductCreate
from app.scrapers.registry import detect_store
from app.services.price_service import get_product_stats, get_price_history
from app.services.backup_service import export_product_csv
from app.scheduler import run_single_product

router = APIRouter(prefix="/products")
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_products(request: Request, store: str = "", status: str = ""):
    db = await get_db()
    try:
        query = "SELECT * FROM products"
        params = []
        conditions = []

        if store:
            conditions.append("store = ?")
            params.append(store)
        if status == "active":
            conditions.append("active = 1")
        elif status == "failing":
            conditions.append("consecutive_failures > 0")
        elif status == "disabled":
            conditions.append("active = 0")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"

        cursor = await db.execute(query, params)
        products = [dict(row) for row in await cursor.fetchall()]

        # Get current price for each
        for p in products:
            cursor2 = await db.execute(
                "SELECT price FROM price_history WHERE product_id = ? AND status = 'success' ORDER BY scraped_at DESC LIMIT 1",
                (p["id"],),
            )
            row = await cursor2.fetchone()
            p["current_price"] = row["price"] if row else None

    finally:
        await db.close()

    return templates.TemplateResponse("products.html", {
        "request": request,
        "products": products,
        "store_filter": store,
        "status_filter": status,
    })


@router.post("/add")
async def add_product(
    name: str = Form(...),
    url: str = Form(...),
    store: str = Form("auto"),
):
    if store == "auto":
        try:
            store = detect_store(url)
        except ValueError:
            raise HTTPException(400, "Could not detect store from URL. Please select manually.")

    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO products (name, url, store) VALUES (?, ?, ?)",
            (name, url, store),
        )
        await db.commit()
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(400, "This URL is already being tracked.")
        raise
    finally:
        await db.close()

    return RedirectResponse("/products", status_code=303)


@router.get("/{product_id}", response_class=HTMLResponse)
async def product_detail(request: Request, product_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        product = await cursor.fetchone()
        if not product:
            raise HTTPException(404, "Product not found")
        product = dict(product)
    finally:
        await db.close()

    stats = await get_product_stats(product_id)
    history = await get_price_history(product_id, limit=200)

    return templates.TemplateResponse("product_detail.html", {
        "request": request,
        "product": product,
        "stats": stats,
        "history": history,
    })


@router.post("/{product_id}/update")
async def update_product(
    product_id: int,
    name: str = Form(None),
    alert_price_abs: float = Form(None),
    alert_price_pct: float = Form(None),
    alert_below_mean: bool = Form(False),
):
    db = await get_db()
    try:
        updates = []
        params = []
        if name:
            updates.append("name = ?")
            params.append(name)
        if alert_price_abs is not None:
            updates.append("alert_price_abs = ?")
            params.append(alert_price_abs)
        if alert_price_pct is not None:
            updates.append("alert_price_pct = ?")
            params.append(alert_price_pct)
        updates.append("alert_below_mean = ?")
        params.append(1 if alert_below_mean else 0)

        params.append(product_id)
        await db.execute(
            f"UPDATE products SET {', '.join(updates)} WHERE id = ?", params
        )
        await db.commit()
    finally:
        await db.close()

    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/{product_id}/toggle")
async def toggle_product(product_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE products SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END, consecutive_failures = 0 WHERE id = ?",
            (product_id,),
        )
        await db.commit()
    finally:
        await db.close()
    return RedirectResponse("/products", status_code=303)


@router.post("/{product_id}/delete")
async def delete_product(product_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await db.commit()
    finally:
        await db.close()
    return RedirectResponse("/products", status_code=303)


@router.post("/{product_id}/scrape")
async def scrape_now(product_id: int):
    await run_single_product(product_id)
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.get("/{product_id}/export")
async def export_csv(product_id: int):
    csv_data = await export_product_csv(product_id)
    return StreamingResponse(
        csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=price_history.csv"},
    )
