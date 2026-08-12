import re
import json
import logging
from typing import Optional
from app.scrapers.base import BaseScraper

logger = logging.getLogger("price_tracker.scraper.shopee")


class ShopeeScraper(BaseScraper):
    store_name = "shopee"

    css_selectors = [
        "[class*='product-price'] [class*='current']",
        "[class*='price'] [class*='current']",
        "[data-sqe='price']",
        "[class*='Price'] [class*='number']",
        "div[class*='product-briefing'] span[class*='price']",
        ".shopee-price--offscreen",
        "[class*='ZEgKB9']",
        "[class*='pqTWkA']",
    ]

    regex_patterns = [
        r'"price"\s*:\s*(\d+)',
        r'"price_min"\s*:\s*(\d+)',
        r'"price_before_discount"\s*:\s*(\d+)',
        r'"display_price"\s*:\s*(\d+)',
        r'"sell_price"\s*:\s*(\d+)',
        r'"current_price"\s*:\s*"?(\d+)"?',
    ]

    async def extract_price(self, url: str) -> Optional[float]:
        from app.browser_manager import browser_manager
        page = await browser_manager.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)

            # Method 1: __NEXT_DATA__ JSON
            price = await self._extract_from_next_data(page)
            if price and price > 0:
                logger.info(f"[shopee] __NEXT_DATA__ price: R$ {price:,.2f}")
                return price

            # Method 2: Wait for price element, then cascade
            try:
                await page.wait_for_selector(
                    "[class*='product-price'], [class*='price'] [class*='current'], [data-sqe='price']",
                    timeout=15000
                )
                await page.wait_for_timeout(2000)
            except Exception:
                await page.wait_for_timeout(5000)

            result = await self.cascade_extract(page, wait_ms=0)
            if result and result.price:
                price = self._normalize_price(result.price, result.method)
                logger.info(f"[shopee] {result.method} price: R$ {price:,.2f}")
                return price

            # Method 3: API data (last resort)
            price = await self._extract_from_api_data(page)
            if price and price > 0:
                logger.info(f"[shopee] API data price: R$ {price:,.2f}")
                return price

            logger.warning(f"[shopee] All extraction methods failed for {url}")
            return None
        finally:
            await browser_manager.close_page(page)

    async def _extract_from_next_data(self, page) -> Optional[float]:
        try:
            script = await page.query_selector('script#__NEXT_DATA__')
            if not script:
                scripts = await page.query_selector_all('script')
                for s in scripts:
                    content = await s.inner_text()
                    if '"price"' in content and '"product_price"' in content:
                        script = s
                        break
                if not script:
                    return None

            content = await script.inner_text()
            data = json.loads(content)

            price = self._dig_for_price(data, ["price", "sell_price", "current_price",
                                                 "product_price", "display_price",
                                                 "price_before_discount"])
            if price:
                return self._normalize_cents(price)
        except Exception as e:
            logger.debug(f"[shopee] __NEXT_DATA__ extraction failed: {e}")
        return None

    def _dig_for_price(self, data, keys: list[str], depth: int = 0) -> Optional[float]:
        if depth > 8:
            return None
        if isinstance(data, dict):
            for key in keys:
                if key in data:
                    val = data[key]
                    if isinstance(val, (int, float)) and val > 0:
                        return float(val)
                    if isinstance(val, str):
                        try:
                            return float(val)
                        except ValueError:
                            pass
            for v in data.values():
                if isinstance(v, (dict, list)):
                    result = self._dig_for_price(v, keys, depth + 1)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = self._dig_for_price(item, keys, depth + 1)
                if result:
                    return result
        return None

    async def _extract_from_api_data(self, page) -> Optional[float]:
        try:
            content = await page.content()
            patterns = [
                r'"price"\s*:\s*(\d{4,})',
                r'"sell_price"\s*:\s*(\d{4,})',
                r'"current_price"\s*:\s*(\d{4,})',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    raw = float(match.group(1))
                    return self._normalize_cents(raw)
        except Exception as e:
            logger.debug(f"Shopee API data extraction failed: {e}")
        return None

    @staticmethod
    def _normalize_cents(price: float) -> float:
        if price > 10000:
            return price / 100
        return price

    @staticmethod
    def _normalize_price(price: float, method: str) -> float:
        if method.startswith("regex") and price > 10000:
            return price / 100
        return price
