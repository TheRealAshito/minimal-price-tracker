import re
import asyncio
from typing import Optional
from app.scrapers.base import BaseScraper


class KabumScraper(BaseScraper):
    store_name = "kabum"

    async def extract_price(self, url: str) -> Optional[float]:
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for price element to appear
            await page.wait_for_timeout(3000)

            # KaBum uses several price selectors
            selectors = [
                "[data-testid='price-value']",
                ".finalPrice",
                ".price .big",
                "[class*='price'] [class*='final']",
                "[class*='Price'] [class*='value']",
            ]

            for selector in selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        price = self.parse_brl_price(text)
                        if price and price > 0:
                            return price
                except Exception:
                    continue

            # Fallback: regex search in page content
            content = await page.content()
            # Look for price patterns in JSON-LD or meta tags
            price_patterns = [
                r'"price"\s*:\s*"?(\d+\.?\d*)"?',
                r'"lowPrice"\s*:\s*"?(\d+\.?\d*)"?',
                r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
            ]
            for pattern in price_patterns:
                match = re.search(pattern, content)
                if match:
                    price = self.parse_brl_price(match.group(1))
                    if price and price > 0:
                        return price

            return None
        finally:
            await page.close()
            await page.context.close()
