import os
import shutil
from datetime import datetime
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from app.database import get_db
from app.config import DB_PATH, settings
from app.services.backup_service import export_backup

router = APIRouter(prefix="/settings")
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        cfg = {row["key"]: row["value"] for row in rows}

        cursor2 = await db.execute("SELECT COUNT(*) as c FROM products")
        product_count = (await cursor2.fetchone())["c"]

        cursor3 = await db.execute("SELECT COUNT(*) as c FROM price_history")
        history_count = (await cursor3.fetchone())["c"]

        db_size = os.path.getsize(str(DB_PATH)) if DB_PATH.exists() else 0
    finally:
        await db.close()

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": cfg,
        "product_count": product_count,
        "history_count": history_count,
        "db_size_mb": round(db_size / (1024 * 1024), 2),
    })


@router.post("/ntfy")
async def update_ntfy(
    ntfy_url: str = Form(""),
    ntfy_port: str = Form(""),
    ntfy_topic: str = Form(""),
):
    db = await get_db()
    try:
        for key, value in [("ntfy_url", ntfy_url), ("ntfy_port", ntfy_port), ("ntfy_topic", ntfy_topic)]:
            await db.execute(
                "UPDATE settings SET value = ? WHERE key = ?", (value, key)
            )
        await db.commit()
    finally:
        await db.close()
    return RedirectResponse("/settings", status_code=303)


@router.post("/interval")
async def update_interval(scrape_interval_hours: int = Form(6)):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE settings SET value = ? WHERE key = 'scrape_interval_hours'",
            (str(scrape_interval_hours),),
        )
        await db.commit()
    finally:
        await db.close()
    return RedirectResponse("/settings", status_code=303)


@router.post("/backup")
async def create_backup():
    path = await export_backup()
    return FileResponse(
        str(path),
        filename=f"price_tracker_backup_{datetime.now().strftime('%Y%m%d')}.db",
        media_type="application/x-sqlite3",
    )


@router.post("/restore")
async def restore(file: UploadFile = File(...)):
    # Save uploaded file temporarily
    temp_path = f"data/restore_{datetime.now().strftime('%Y%m%d%H%M%S')}.db"
    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Verify it's a valid SQLite DB
    try:
        import sqlite3
        conn = sqlite3.connect(temp_path)
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        conn.close()
    except Exception:
        os.remove(temp_path)
        return RedirectResponse("/settings?error=invalid_db", status_code=303)

    # Backup current before restore
    await export_backup()

    # Restore
    shutil.copy2(temp_path, str(DB_PATH))
    os.remove(temp_path)

    return RedirectResponse("/settings?restored=1", status_code=303)
