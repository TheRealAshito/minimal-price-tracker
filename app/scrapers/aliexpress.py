import re
from typing import Optional
from app.scrapers.base import BaseScraper


class AliExpressScraper(BaseScraper):
    store_name = "aliexpress"

    async def extract_price(self, url: str) -> Optional[float]:
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(5000)

            # AliExpress uses several price selectors
            selectors = [
                "[class*='product-price'] [class*='current']",
                "[class*='Price'] [class*='value']",
                "[class*='price'] [class*='current']",
                ".product-price-value",
                "[class*='ProductPrice']",
                "span[class*='price']",
            ]

            for selector in selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        text = await element.inner_text()
                        price = self._parse_ali_price(text)
                        if price and price > 0:
                            return price
                except Exception:
                    continue

            # Fallback: search page source for price JSON
            content = await page.content()
            patterns = [
                r'"formattedPrice"\s*:\s*"R\$\s*([\d.,]+)"',
                r'"minPrice"\s*:\s*"?([\d.,]+)"?',
                r'"maxPrice"\s*:\s*"?([\d.,]+)"?',
                r'"price"\s*:\s*"?([\d.,]+)"?',
                r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    price = self._parse_ali_price(match.group(1))
                    if price and price > 0:
                        return price

            return None
        finally:
            await page.close()
            await page.context.close()

    @staticmethod
    def _parse_ali_price(text: str) -> Optional[float]:
        """Parse price from AliExpress (handles both BRL and USD formats)."""
        if not text:
            return None
        # Remove currency symbols
        cleaned = text.replace("R$", "").replace("US$", "").replace("$", "").strip()

        # Check if it's BRL format (1.299,90) or USD format (1,299.90)
        if re.search(r'\d+\.\d{3},\d{2}', cleaned):
            # BRL format: 1.299,90
            cleaned = re.sub(r'\.(?=\d{3})', '', cleaned).replace(',', '.')
        elif re.search(r'\d+,\d{3}\.\d{2}', cleaned):
            # USD format: 1,299.90
            cleaned = cleaned.replace(',', '')
        else:
            # Simple format: just remove commas that might be thousands sep
            cleaned = cleaned.replace(',', '.')

        match = re.search(r'(\d+\.?\d*)', cleaned)
        if match:
            return float(match.group(1))
        return None
