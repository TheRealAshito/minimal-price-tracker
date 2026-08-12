from typing import Optional
from app.scrapers.base import BaseScraper


class TerabyteScraper(BaseScraper):
    store_name = "terabyte"

    css_selectors = [
        ".product-price .final-price",
        ".product-price .value",
        "[class*='price'] [class*='final']",
        "[class*='Price'] [class*='value']",
        ".prod-purchase-price",
        ".prod-old-price + .prod-new-price",
        "span[class*='price']",
        "[itemprop='price']",
        "[data-price]",
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
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            result = await self.cascade_extract(page, wait_ms=4000)
            return result.price if result else None
        finally:
            await browser_manager.close_page(page)
