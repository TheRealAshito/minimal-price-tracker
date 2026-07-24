from app.scrapers.base import BaseScraper
from app.scrapers.kabum import KabumScraper
from app.scrapers.shopee import ShopeeScraper
from app.scrapers.amazon import AmazonScraper

SCRAPERS = {
    "kabum": KabumScraper,
    "shopee": ShopeeScraper,
    "amazon": AmazonScraper,
}


def get_scraper(store: str) -> BaseScraper:
    scraper_class = SCRAPERS.get(store)
    if not scraper_class:
        raise ValueError(f"Unknown store: {store}")
    return scraper_class()


def detect_store(url: str) -> str:
    """Auto-detect store from URL."""
    url_lower = url.lower()
    if "kabum.com.br" in url_lower:
        return "kabum"
    elif "shopee.com.br" in url_lower or "shopee." in url_lower:
        return "shopee"
    elif "amazon.com.br" in url_lower or "amazon." in url_lower:
        return "amazon"
    raise ValueError(f"Could not detect store from URL: {url}")
