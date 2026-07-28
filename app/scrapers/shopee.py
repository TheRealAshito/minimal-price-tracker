from typing import Optional
from app.scrapers.base import BaseScraper


class ShopeeScraper(BaseScraper):
    store_name = "shopee"

    css_selectors = [
        "[class*='product-price'] [class*='current']",
        "[class*='price'] [class*='current']",
        ".pqTWkA",
        "[data-sqe='price']",
        "[class*='Price'] [class*='number']",
        "div[class*='product-briefing'] span[class*='price']",
    ]

    regex_patterns = [
        r'"price"\s*:\s*(\d+)',
        r'"price_min"\s*:\s*(\d+)',
        r'"price_before_discount"\s*:\s*(\d+)',
        r'"display_price"\s*:\s*(\d+)',
    ]

    async def extract_price(self, url: str) -> Optional[float]:
        page = await self._get_page()
        try:
            # Shopee needs longer wait for JS rendering
            await page.goto(url, wait_until="networkidle", timeout=45000)
            result = await self.cascade_extract(page, wait_ms=5000)

            if result and result.price:
                # Shopee prices are often in cents
                if result.price > 10000 and result.method.startswith("regex"):
                    result.price = result.price / 100
                return result.price

            return None
        finally:
            await page.close()
            await page.context.close()
