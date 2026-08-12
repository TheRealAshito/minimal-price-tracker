from typing import Optional
from app.scrapers.base import BaseScraper


class KabumScraper(BaseScraper):
    store_name = "kabum"

    css_selectors = [
        "[data-testid='price-value']",
        ".finalPrice",
        ".price .big",
        "[class*='price'] [class*='final']",
        "[class*='Price'] [class*='value']",
        "[class*='sc-fTFjTM']",  # KaBum styled-components
    ]

    regex_patterns = [
        r'"price"\s*:\s*"?(\d+\.?\d*)"?',
        r'"lowPrice"\s*:\s*"?(\d+\.?\d*)"?',
        r'"sellingPrice"\s*:\s*"?(\d+[.,]?\d*)"?',
        r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
    ]

    async def extract_price(self, url: str) -> Optional[float]:
        from app.browser_manager import browser_manager
        page = await browser_manager.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            result = await self.cascade_extract(page, wait_ms=3000)
            return result.price if result else None
        finally:
            await browser_manager.close_page(page)
