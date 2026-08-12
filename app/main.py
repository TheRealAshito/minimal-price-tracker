import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.database import init_db, get_db
from app.routers import dashboard, products, alerts, settings, api
from app.routers import logs as logs_router
from app.routers import picker as picker_router
from app.scheduler import start_scheduler, stop_scheduler
from app.config import settings as app_settings
from app.log_buffer import setup_log_buffer, get_errors, get_log_stats
from app.memory_diagnostics import get_memory_report, log_memory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Setup in-memory log buffer for the web UI
setup_log_buffer()

logger = logging.getLogger("price_tracker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_memory("app_startup")
    logger.info("Initializing database...")
    await init_db()
    logger.info(f"Starting scheduler (interval: {app_settings.scrape_interval_hours}h)...")
    start_scheduler(app_settings.scrape_interval_hours)
    log_memory("scheduler_started")
    yield
    logger.info("Shutting down scheduler...")
    stop_scheduler()
    log_memory("app_shutdown")


app = FastAPI(
    title="Minimal Price Tracker",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Global exception handler ──────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions, log with traceback, return structured error."""
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_str = "".join(tb)
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}\n{tb_str}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "path": request.url.path,
            "method": request.method,
            "detail": "Check /logs?level=ERROR or /debug/errors for details.",
        },
    )


# ── Debug endpoints ───────────────────────────────────────────────
@app.get("/debug/errors")
async def debug_errors(limit: int = 50):
    """Return recent ERROR+ log entries with tracebacks."""
    return JSONResponse({
        "errors": get_errors(limit=limit),
        "stats": get_log_stats(),
    })


@app.get("/debug/stats")
async def debug_stats():
    """Return log buffer stats and system info."""
    import sys
    return JSONResponse({
        "log_stats": get_log_stats(),
        "python": sys.version,
        "app_version": "1.0.0",
    })


@app.get("/debug/memory")
async def debug_memory():
    """Return detailed memory diagnostics."""
    return JSONResponse(get_memory_report())


app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ── Middleware: inject date_format into every request ──────────────
@app.middleware("http")
async def inject_date_format(request: Request, call_next):
    """Read date_format setting and make it available in templates."""
    try:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT value FROM settings WHERE key = 'date_format'")
            row = await cursor.fetchone()
            request.state.date_format = row["value"] if row else "DD/MM/YYYY"
        finally:
            await db.close()
    except Exception:
        request.state.date_format = "DD/MM/YYYY"
    response = await call_next(request)
    return response

app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(alerts.router)
app.include_router(settings.router)
app.include_router(api.router)
app.include_router(logs_router.router)
app.include_router(picker_router.router)
