from typing import Optional
from app.scrapers.base import BaseScraper


class AmazonScraper(BaseScraper):
    store_name = "amazon"

    css_selectors = [
        ".a-price .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#priceblock_saleprice",
        "[data-a-color='price'] .a-offscreen",
        "#corePrice_feature_div .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        ".a-price:not([data-a-strike]) .a-offscreen",
    ]

    regex_patterns = [
        r'"price"\s*:\s*"?(\d+[.,]?\d*)"?\s*,\s*"priceCurrency"\s*:\s*"BRL"',
        r'"lowPrice"\s*:\s*"?(\d+[.,]?\d*)"?',
        r'"price"\s*:\s*"?(\d+[.,]?\d*)"?',
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
