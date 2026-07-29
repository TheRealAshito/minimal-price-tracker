import re
import json
import random
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page

logger = logging.getLogger("price_tracker.scraper")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]


@dataclass
class ExtractionResult:
    """Result from a price extraction attempt."""
    price: Optional[float] = None
    method: str = ""
    confidence: float = 0.0  # 0.0 to 1.0
    raw_text: str = ""


class BaseScraper(ABC):
    store_name: str

    # Subclasses override these for cascade extraction
    css_selectors: list[str] = field(default_factory=list) if False else []
    jsonld_price_keys: list[str] = ["price", "lowPrice", "highPrice"]
    meta_price_selectors: list[str] = [
        'meta[property="product:price:amount"]',
        'meta[name="price"]',
        'meta[itemprop="price"]',
    ]
    regex_patterns: list[str] = field(default_factory=list) if False else []

    def __init__(self):
        self._browser: Optional[Browser] = None
        self._playwright = None

    async def _get_browser(self):
        if self._browser is None or not self._browser.is_connected():
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
        return self._browser

    async def _get_page(self):
        browser = await self._get_browser()
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1920, "height": 1080},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        page = await context.new_page()

        # Apply stealth
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except Exception:
            logger.debug("Stealth patch not available, continuing without it")

        return page

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

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
            # Check for direct price keys
            for key in self.jsonld_price_keys:
                if key in data:
                    val = data[key]
                    if isinstance(val, (int, float)) and val > 0:
                        return float(val)
                    if isinstance(val, str):
                        price = self.parse_brl_price(val)
                        if price and price > 0:
                            return price
            # Check offers
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
            # Recurse into nested dicts
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

        Returns the first successful result, or None if all fail.
        Subclasses can override css_selectors and regex_patterns.
        """
        await page.wait_for_timeout(wait_ms)

        # Step 1: CSS selectors
        if self.css_selectors:
            result = await self._try_css_selectors(page, self.css_selectors)
            if result:
                logger.debug(f"[{self.store_name}] CSS match: {result.method} → R$ {result.price}")
                return result

        # Step 2: JSON-LD
        result = await self._try_jsonld(page)
        if result:
            logger.debug(f"[{self.store_name}] JSON-LD match → R$ {result.price}")
            return result

        # Step 3: Meta tags
        result = await self._try_meta_tags(page)
        if result:
            logger.debug(f"[{self.store_name}] Meta match → R$ {result.price}")
            return result

        # Step 4: Regex
        if self.regex_patterns:
            result = await self._try_regex(page)
            if result:
                logger.debug(f"[{self.store_name}] Regex match → R$ {result.price}")
                return result

        logger.warning(f"[{self.store_name}] All extraction methods failed")
        return None

    # ─── Abstract / legacy interface ──────────────────────────────────

    async def _try_custom_selector_url(self, url: str, selector: str) -> Optional[float]:
        """
        Try extracting price from a URL using a custom CSS selector.
        Opens a new page, navigates, queries the selector, parses BRL price.
        Used by scrape() as the first extraction attempt when custom_selector is set.
        """
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            element = await page.query_selector(selector)
            if not element:
                return None

            # Try inner_text first
            text = await element.inner_text()
            if text:
                price = self.parse_brl_price(text.strip())
                if price and price > 0:
                    return price

            # Try textContent (captures hidden text nodes)
            text = await element.evaluate("el => el.textContent")
            if text:
                price = self.parse_brl_price(text.strip())
                if price and price > 0:
                    return price

            # Try value attribute (for input elements)
            value = await element.get_attribute("value")
            if value:
                price = self.parse_brl_price(value.strip())
                if price and price > 0:
                    return price

        except Exception as e:
            logger.debug(f"[{self.store_name}] Custom selector error: {e}")
        finally:
            await page.close()
            await page.context.close()
        return None

    @abstractmethod
    async def extract_price(self, url: str) -> Optional[float]:
        """Extract price from URL. Returns price as float or None if failed."""
        pass

    async def scrape(self, url: str, custom_selector: Optional[str] = None) -> tuple[Optional[float], Optional[str]]:
        """
        Main scrape method. Returns (price, error_message).
        If custom_selector is provided, tries it FIRST before falling back
        to the store-specific extract_price method.
        """
        try:
            # Step 1: Try custom selector if provided
            if custom_selector:
                price = await self._try_custom_selector_url(url, custom_selector)
                if price is not None:
                    logger.info(f"[{self.store_name}] Custom selector override: R$ {price:,.2f}")
                    return price, None
                logger.debug(f"[{self.store_name}] Custom selector didn't match, falling back to store logic")

            # Step 2: Fall back to store-specific extraction
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
        # Remove currency symbol and whitespace
        cleaned = text.replace("R$", "").replace("r$", "").replace("BRL", "").strip()
        # Remove thousands separator (.) and convert decimal comma (,) to dot
        cleaned = re.sub(r"\.(?=\d{3})", "", cleaned)
        cleaned = cleaned.replace(",", ".")
        # Extract first number
        match = re.search(r"(\d+\.?\d*)", cleaned)
        if match:
            price = float(match.group(1))
            # Sanity bounds: reject prices outside plausible BRL range
            if 0.50 <= price <= 1_000_000:
                return price
        return None
