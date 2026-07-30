import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.database import init_db
from app.routers import dashboard, products, alerts, settings, api
from app.routers import logs as logs_router
from app.routers import picker as picker_router
from app.scheduler import start_scheduler, stop_scheduler
from app.config import settings as app_settings
from app.log_buffer import setup_log_buffer, get_errors, get_log_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# Setup in-memory log buffer for the web UI
setup_log_buffer()

logger = logging.getLogger("price_tracker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    await init_db()
    logger.info(f"Starting scheduler (interval: {app_settings.scrape_interval_hours}h)...")
    start_scheduler(app_settings.scrape_interval_hours)
    yield
    logger.info("Shutting down scheduler...")
    stop_scheduler()


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


app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(alerts.router)
app.include_router(settings.router)
app.include_router(api.router)
app.include_router(logs_router.router)
app.include_router(picker_router.router)
