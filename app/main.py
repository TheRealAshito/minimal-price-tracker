import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.database import init_db
from app.routers import dashboard, products, alerts, settings, api
from app.routers import logs as logs_router
from app.routers import picker as picker_router
from app.scheduler import start_scheduler, stop_scheduler
from app.config import settings as app_settings
from app.log_buffer import setup_log_buffer

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

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(products.router)
app.include_router(alerts.router)
app.include_router(settings.router)
app.include_router(api.router)
app.include_router(logs_router.router)
app.include_router(picker_router.router)
