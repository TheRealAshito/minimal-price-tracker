import re
from typing import Optional
from app.scrapers.base import BaseScraper


class AmazonScraper(BaseScraper):
    store_name = "amazon"

    async def extract_price(self, url: str) -> Optional[float]:
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(4000)

            # Amazon Brazil price selectors
            selectors = [
                ".a-price .a-offscreen",
                "#priceblock_ourprice",
                "#priceblock_dealprice",
                "#priceblock_saleprice",
                ".a-price-whole",
                "[data-a-color='price'] .a-offscreen",
                "#corePrice_feature_div .a-offscreen",
                "#corePriceDisplay_desktop_feature_div .a-offscreen",
                ".a-price:not([data-a-strike]) .a-offscreen",
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

            # Fallback: JSON-LD structured data
            content = await page.content()
            patterns = [
                r'"price"\s*:\s*"?(\d+[\.,]?\d*)"?\s*,\s*"priceCurrency"\s*:\s*"BRL"',
                r'"lowPrice"\s*:\s*"?(\d+[\.,]?\d*)"?',
                r'"price"\s*:\s*"?(\d+[\.,]?\d*)"?',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    price = self.parse_brl_price(match.group(1))
                    if price and price > 0:
                        return price

            return None
        finally:
            await page.close()
            await page.context.close()
