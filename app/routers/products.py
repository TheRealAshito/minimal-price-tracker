from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.scrapers.registry import detect_store
from app.services.price_service import get_product_stats, get_price_history, get_link_stats, get_link_price_history
from app.services.backup_service import export_product_csv
from app.scheduler import run_single_product, run_single_link

router = APIRouter(prefix="/products")
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def list_products(request: Request, store: str = "", status: str = ""):
    db = await get_db()
    try:
        # Get all products with their links
        cursor = await db.execute("""
            SELECT p.*, COUNT(pl.id) as link_count,
                   GROUP_CONCAT(DISTINCT pl.store) as stores
            FROM products p
            LEFT JOIN product_links pl ON pl.product_id = p.id
        """ + (" WHERE pl.store = ? " if store else " ") + """
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """, [store] if store else [])
        products = [dict(row) for row in await cursor.fetchall()]

        # Get current best price for each product
        for p in products:
            cursor2 = await db.execute("""
                SELECT ph.price, pl.store FROM price_history ph
                JOIN product_links pl ON pl.id = ph.link_id
                WHERE pl.product_id = ? AND ph.status = 'success' AND ph.price IS NOT NULL
                ORDER BY ph.scraped_at DESC
            """, (p["id"],))
            rows = await cursor2.fetchall()
            store_prices = {}
            for r in rows:
                if r["store"] not in store_prices:
                    store_prices[r["store"]] = r["price"]
            p["store_prices"] = store_prices
            p["best_price"] = min(store_prices.values()) if store_prices else None

            # Status filter
            if status == "active" and not p["active"]:
                products = [x for x in products if x["active"]]
            elif status == "disabled" and p["active"]:
                products = [x for x in products if not x["active"]]

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
):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO products (name) VALUES (?)",
            (name,),
        )
        await db.commit()
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

        # Get all links for this product
        cursor2 = await db.execute(
            "SELECT * FROM product_links WHERE product_id = ? ORDER BY created_at DESC",
            (product_id,),
        )
        links = [dict(row) for row in await cursor2.fetchall()]

        # Get latest price + stats for each link
        for link in links:
            cursor3 = await db.execute(
                "SELECT price FROM price_history WHERE link_id = ? AND status = 'success' ORDER BY scraped_at DESC LIMIT 1",
                (link["id"],),
            )
            row = await cursor3.fetchone()
            link["current_price"] = row["price"] if row else None

            # Get failure count
            cursor4 = await db.execute(
                "SELECT consecutive_failures FROM product_links WHERE id = ?",
                (link["id"],),
            )
            fail_row = await cursor4.fetchone()
            link["consecutive_failures"] = fail_row["consecutive_failures"] if fail_row else 0

    finally:
        await db.close()

    stats = await get_product_stats(product_id)
    history = await get_price_history(product_id, limit=200)

    return templates.TemplateResponse("product_detail.html", {
        "request": request,
        "product": product,
        "links": links,
        "stats": stats.model_dump(),
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


@router.post("/{product_id}/add-link")
async def add_link(
    product_id: int,
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
        # Check product exists
        cursor = await db.execute("SELECT id FROM products WHERE id = ?", (product_id,))
        if not await cursor.fetchone():
            raise HTTPException(404, "Product not found")

        await db.execute(
            "INSERT INTO product_links (product_id, url, store) VALUES (?, ?, ?)",
            (product_id, url, store),
        )
        await db.commit()
    except Exception as e:
        if "UNIQUE" in str(e):
            raise HTTPException(400, "This URL is already being tracked.")
        raise
    finally:
        await db.close()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/{product_id}/toggle")
async def toggle_product(product_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE products SET active = CASE WHEN active = 1 THEN 0 ELSE 1 END WHERE id = ?",
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
async def scrape_product_now(product_id: int):
    await run_single_product(product_id)
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/{product_id}/links/{link_id}/scrape")
async def scrape_link_now(product_id: int, link_id: int):
    await run_single_link(link_id)
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.post("/{product_id}/links/{link_id}/delete")
async def delete_link(product_id: int, link_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM product_links WHERE id = ? AND product_id = ?",
                         (link_id, product_id))
        await db.commit()
    finally:
        await db.close()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@router.get("/{product_id}/export")
async def export_csv(product_id: int):
    csv_data = await export_product_csv(product_id)
    return StreamingResponse(
        csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=price_history.csv"},
    )
