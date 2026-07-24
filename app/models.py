from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ProductCreate(BaseModel):
    name: str
    url: str
    store: str
    alert_price_abs: Optional[float] = None
    alert_price_pct: Optional[float] = None
    alert_below_mean: bool = False


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    alert_price_abs: Optional[float] = None
    alert_price_pct: Optional[float] = None
    alert_below_mean: Optional[bool] = None
    active: Optional[bool] = None


class Product(BaseModel):
    id: int
    name: str
    url: str
    store: str
    alert_price_abs: Optional[float]
    alert_price_pct: Optional[float]
    alert_below_mean: bool
    consecutive_failures: int
    active: bool
    created_at: str


class PriceRecord(BaseModel):
    id: int
    product_id: int
    price: Optional[float]
    status: str
    error_message: Optional[str]
    scraped_at: str


class PriceStats(BaseModel):
    current_price: Optional[float]
    min_price: Optional[float]
    max_price: Optional[float]
    mean_price: Optional[float]
    median_price: Optional[float]
    std_dev: Optional[float]
    total_records: int
    first_tracked: Optional[str]
    last_updated: Optional[str]


class SettingsUpdate(BaseModel):
    ntfy_url: Optional[str] = None
    ntfy_port: Optional[str] = None
    ntfy_topic: Optional[str] = None
    scrape_interval_hours: Optional[int] = None
