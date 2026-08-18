"""
Pichau scraper.
Pichau uses aggressive anti-bot detection (shows a pigeon image).
FlareSolverr fallback is critical for this store.
"""
import logging
from typing import Optional
from app.scrapers.base import BaseScraper

logger = logging.getLogger("price_tracker.scraper.pichau")


class PichauScraper(BaseScraper):
    store_name = "pichau"

    css_selectors = [
        # Pichau price selectors (common patterns)
        "[data-testid='price']",
        ".product-price .final-price",
        ".product-price .value",
        "[class*='price'] [class*='final']",
        "[class*='Price'] [class*='value']",
        "[class*='price'] [class*='current']",
        "span[class*='price']",
        "[itemprop='price']",
        "[data-price]",
        ".prod-purchase-price",
        ".prod-old-price + .prod-new-price",
        # Pichau specific (best guesses — element picker is recommended)
        "[class*='jss'] [class*='price']",
        "[class*='MuiTypography'][class*='price']",
    ]

    meta_price_selectors = [
        'meta[property="product:price:amount"]',
        'meta[name="price"]',
        'meta[itemprop="price"]',
        'meta[property="og:price:amount"]',
    ]

    regex_patterns = [
        r'"price"\s*:\s*"?(\d+[.,]?\d*)"?',
        r'"lowPrice"\s*:\s*"?(\d+[.,]?\d*)"?',
        r'"sellingPrice"\s*:\s*"?(\d+[.,]?\d*)"?',
        r'"finalPrice"\s*:\s*"?(\d+[.,]?\d*)"?',
        r'data-price="(\d+[.,]?\d*)"',
        r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
    ]

    async def extract_price(self, url: str) -> Optional[float]:
        from app.browser_manager import browser_manager
        page = await browser_manager.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            result = await self.cascade_extract(page, wait_ms=5000)
            return result.price if result else None
        finally:
            await browser_manager.close_page(page)
