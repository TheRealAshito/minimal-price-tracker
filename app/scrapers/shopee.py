import re
from typing import Optional
from app.scrapers.base import BaseScraper


class ShopeeScraper(BaseScraper):
    store_name = "shopee"

    async def extract_price(self, url: str) -> Optional[float]:
        page = await self._get_page()
        try:
            # Shopee needs longer wait for JS rendering
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(5000)

            # Try common Shopee price selectors
            selectors = [
                "[class*='product-price'] [class*='current']",
                "[class*='price'] [class*='current']",
                ".pqTWkA",  # Shopee price class (changes frequently)
                "[data-sqe='price']",
                "[class*='Price'] [class*='number']",
                "div[class*='product-briefing'] span[class*='price']",
            ]

            for selector in selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        text = await element.inner_text()
                        price = self.parse_brl_price(text)
                        if price and price > 0:
                            return price
                except Exception:
                    continue

            # Fallback: search page source for price JSON
            content = await page.content()
            patterns = [
                r'"price"\s*:\s*(\d+)',
                r'"price_min"\s*:\s*(\d+)',
                r'"price_before_discount"\s*:\s*(\d+)',
                r'"display_price"\s*:\s*(\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    # Shopee prices are often in cents
                    raw = int(match.group(1))
                    if raw > 10000:  # likely in cents
                        return raw / 100
                    return float(raw)

            return None
        finally:
            await page.close()
            await page.context.close()
