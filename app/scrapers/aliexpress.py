import re
from typing import Optional
from app.scrapers.base import BaseScraper


class AliExpressScraper(BaseScraper):
    store_name = "aliexpress"

    css_selectors = [
        "[class*='product-price'] [class*='current']",
        "[class*='Price'] [class*='value']",
        "[class*='price'] [class*='current']",
        ".product-price-value",
        "[class*='ProductPrice']",
        "span[class*='price']",
    ]

    regex_patterns = [
        r'"formattedPrice"\s*:\s*"R\$\s*([\d.,]+)"',
        r'"minPrice"\s*:\s*"?([\d.,]+)"?',
        r'"maxPrice"\s*:\s*"?([\d.,]+)"?',
        r'"price"\s*:\s*"?([\d.,]+)"?',
        r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
    ]

    async def extract_price(self, url: str) -> Optional[float]:
        from app.browser_manager import browser_manager
        page = await browser_manager.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            result = await self.cascade_extract(page, wait_ms=5000)
            if result and result.price:
                return result.price
            return None
        finally:
            await browser_manager.close_page(page)
