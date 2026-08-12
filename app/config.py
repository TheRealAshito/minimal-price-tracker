from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "Minimal Price Tracker"
    database_url: str = "data/prices.db"
    scrape_interval_hours: int = 6
    max_consecutive_failures: int = 10
    alert_failure_threshold: int = 3
    max_history_days: int = 365
    timezone: str = "America/Sao_Paulo"

    class Config:
        env_file = ".env"


settings = Settings()
DB_PATH = Path(settings.database_url)
