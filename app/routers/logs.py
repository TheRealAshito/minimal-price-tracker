from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from app.log_buffer import get_logs, get_log_stats

router = APIRouter(prefix="/logs")
from app.templates_config import templates


@router.get("", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    level: str = Query("", alias="level"),
    limit: int = Query(200, alias="limit"),
):
    entries = get_logs(level=level or None, limit=limit)
    stats = get_log_stats()
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "entries": entries,
        "stats": stats,
        "level_filter": level,
        "limit": limit,
    })


@router.get("/api")
async def logs_api(
    level: str = Query("", alias="level"),
    limit: int = Query(200, alias="limit"),
):
    entries = get_logs(level=level or None, limit=limit)
    stats = get_log_stats()
    return JSONResponse({"entries": entries, "stats": stats})
