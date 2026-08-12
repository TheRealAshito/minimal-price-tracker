import re
import json
import random
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("price_tracker.scraper")


class ExtractionResult:
    """Result from a price extraction attempt."""

    def __init__(self, price=None, method="", confidence=0.0, raw_text=""):
        self.price = price
        self.method = method
        self.confidence = confidence
        self.raw_text = raw_text


class BaseScraper(ABC):
    store_name: str

    # Subclasses override these for cascade extraction
    css_selectors: list[str] = []
    jsonld_price_keys: list[str] = ["price", "lowPrice", "highPrice"]
    meta_price_selectors: list[str] = [
        'meta[property="product:price:amount"]',
        'meta[name="price"]',
        'meta[itemprop="price"]',
    ]
    regex_patterns: list[str] = []

    # ─── Cascade extraction methods ───────────────────────────────────

    async def _try_css_selectors(self, page, selectors: list[str]) -> Optional[ExtractionResult]:
        """Step 1: Try CSS selectors in priority order."""
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    price = self.parse_brl_price(text)
                    if price and price > 0:
                        return ExtractionResult(
                            price=price, method=f"css:{selector}",
                            confidence=0.95, raw_text=text.strip()
                        )
            except Exception:
                continue
        return None

    async def _try_jsonld(self, page) -> Optional[ExtractionResult]:
        """Step 2: Extract price from JSON-LD structured data."""
        try:
            scripts = await page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                content = await script.inner_text()
                try:
                    data = json.loads(content)
                    price = self._extract_from_jsonld(data)
                    if price and price > 0:
                        return ExtractionResult(
                            price=price, method="jsonld",
                            confidence=0.90, raw_text=str(price)
                        )
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            logger.debug("JSON-LD extraction failed on page")
        return None

    def _extract_from_jsonld(self, data, depth=0) -> Optional[float]:
        """Recursively search JSON-LD for price values."""
        if depth > 5:
            return None
        if isinstance(data, dict):
            for key in self.jsonld_price_keys:
                if key in data:
                    val = data[key]
                    if isinstance(val, (int, float)) and val > 0:
                        return float(val)
                    if isinstance(val, str):
                        price = self.parse_brl_price(val)
                        if price and price > 0:
                            return price
            if "offers" in data:
                offers = data["offers"]
                if isinstance(offers, list):
                    for offer in offers:
                        result = self._extract_from_jsonld(offer, depth + 1)
                        if result:
                            return result
                elif isinstance(offers, dict):
                    result = self._extract_from_jsonld(offers, depth + 1)
                    if result:
                        return result
            for v in data.values():
                if isinstance(v, (dict, list)):
                    result = self._extract_from_jsonld(v, depth + 1)
                    if result:
                        return result
        elif isinstance(data, list):
            for item in data:
                result = self._extract_from_jsonld(item, depth + 1)
                if result:
                    return result
        return None

    async def _try_meta_tags(self, page, selectors: Optional[list[str]] = None) -> Optional[ExtractionResult]:
        """Step 3: Extract price from meta tags."""
        selectors = selectors if selectors is not None else self.meta_price_selectors
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    content = await element.get_attribute("content")
                    if content:
                        price = self.parse_brl_price(content)
                        if price and price > 0:
                            return ExtractionResult(
                                price=price, method=f"meta:{selector}",
                                confidence=0.85, raw_text=content
                            )
            except Exception:
                continue
        return None

    async def _try_regex(self, page, patterns: Optional[list[str]] = None) -> Optional[ExtractionResult]:
        """Step 4: Regex search on page source as last resort."""
        patterns = patterns if patterns is not None else self.regex_patterns
        if not patterns:
            return None
        try:
            content = await page.content()
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    price = self.parse_brl_price(match.group(1))
                    if price and price > 0:
                        return ExtractionResult(
                            price=price, method=f"regex:{pattern[:30]}",
                            confidence=0.60, raw_text=match.group(0)[:100]
                        )
        except Exception:
            logger.debug("Regex extraction failed on page content")
        return None

    async def cascade_extract(self, page, wait_ms: int = 3000) -> Optional[ExtractionResult]:
        """
        Run the full cascade extraction pipeline:
        1. CSS selectors (highest confidence)
        2. JSON-LD structured data
        3. Meta tags
        4. Regex on page source (lowest confidence)
        """
        await page.wait_for_timeout(wait_ms)

        if self.css_selectors:
            result = await self._try_css_selectors(page, self.css_selectors)
            if result:
                logger.debug(f"[{self.store_name}] CSS match: {result.method} -> R$ {result.price}")
                return result

        result = await self._try_jsonld(page)
        if result:
            logger.debug(f"[{self.store_name}] JSON-LD match -> R$ {result.price}")
            return result

        result = await self._try_meta_tags(page)
        if result:
            logger.debug(f"[{self.store_name}] Meta match -> R$ {result.price}")
            return result

        if self.regex_patterns:
            result = await self._try_regex(page)
            if result:
                logger.debug(f"[{self.store_name}] Regex match -> R$ {result.price}")
                return result

        logger.warning(f"[{self.store_name}] All extraction methods failed")
        return None

    # ─── Pre-actions replay ───────────────────────────────────────────

    async def _replay_pre_actions(self, page, actions: list):
        """Replay recorded pre-scrape actions (click, scroll, wait, type, goto)."""
        if not actions:
            return
        for action in actions:
            try:
                atype = action.get("type")
                if atype == "click":
                    x, y = action.get("x", 0), action.get("y", 0)
                    await page.mouse.click(x, y)
                    await page.wait_for_timeout(2000)
                elif atype == "scroll":
                    direction = action.get("direction", "down")
                    amount = action.get("amount", 3)
                    for _ in range(amount):
                        await page.mouse.wheel(0, 300 if direction == "down" else -300)
                        await page.wait_for_timeout(200)
                    await page.wait_for_timeout(1000)
                elif atype == "wait":
                    await page.wait_for_timeout(action.get("ms", 3000))
                elif atype == "type":
                    await page.keyboard.type(action.get("text", ""), delay=50)
                elif atype == "goto":
                    await page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                logger.debug(f"[{self.store_name}] Replayed pre-action: {atype}")
            except Exception as e:
                logger.warning(f"[{self.store_name}] Pre-action {action.get('type')} failed: {e}")

    async def _try_custom_selector_url(self, url: str, selector: str, pre_actions: Optional[list] = None) -> Optional[float]:
        """
        Try extracting price from a URL using a custom CSS selector.
        Uses the shared browser manager. Only closes the page, not the context.
        """
        from app.browser_manager import browser_manager

        page = await browser_manager.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            if pre_actions:
                await self._replay_pre_actions(page, pre_actions)

            element = await page.query_selector(selector)
            if not element:
                return None

            text = await element.inner_text()
            if text:
                price = self.parse_brl_price(text.strip())
                if price and price > 0:
                    return price

            text = await element.evaluate("el => el.textContent")
            if text:
                price = self.parse_brl_price(text.strip())
                if price and price > 0:
                    return price

            value = await element.get_attribute("value")
            if value:
                price = self.parse_brl_price(value.strip())
                if price and price > 0:
                    return price

        except Exception as e:
            logger.debug(f"[{self.store_name}] Custom selector error: {e}")
        finally:
            await browser_manager.close_page(page)
        return None

    # ─── Abstract / main interface ────────────────────────────────────

    @abstractmethod
    async def extract_price(self, url: str) -> Optional[float]:
        """Extract price from URL. Uses shared browser via browser_manager."""
        pass

    async def scrape(self, url: str, custom_selector: Optional[str] = None, pre_actions: Optional[list] = None) -> tuple[Optional[float], Optional[str]]:
        """
        Main scrape method. Returns (price, error_message).
        If custom_selector is provided, tries it FIRST before falling back
        to the store-specific extract_price method.
        """
        try:
            if custom_selector:
                price = await self._try_custom_selector_url(url, custom_selector, pre_actions=pre_actions)
                if price is not None:
                    logger.info(f"[{self.store_name}] Custom selector override: R$ {price:,.2f}")
                    return price, None
                logger.debug(f"[{self.store_name}] Custom selector didn't match, falling back to store logic")

            price = await self.extract_price(url)
            if price is None:
                return None, "Could not extract price from page"
            return price, None
        except Exception as e:
            return None, str(e)[:500]

    @staticmethod
    def parse_brl_price(text: str) -> Optional[float]:
        """Parse Brazilian Real price from text like 'R$ 1.299,90' or '1299.90'."""
        if not text:
            return None
        cleaned = text.replace("R$", "").replace("r$", "").replace("BRL", "").strip()
        cleaned = re.sub(r"\.(?=\d{3})", "", cleaned)
        cleaned = cleaned.replace(",", ".")
        match = re.search(r"(\d+\.?\d*)", cleaned)
        if match:
            price = float(match.group(1))
            if 0.50 <= price <= 1_000_000:
                return price
        return None
