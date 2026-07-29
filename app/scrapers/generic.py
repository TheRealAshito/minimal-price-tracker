"""
Generic scraper for any website.
Uses a user-picked CSS selector (custom_selector) as primary extraction method,
falls back to the cascade pipeline (CSS -> JSON-LD -> meta -> regex) if the
custom selector fails or is not set.

This scraper is used when store='generic' (any URL not in the 5 known stores).
For known stores, the store-specific scraper is used, but custom_selector still
takes priority via BaseScraper.scrape().
"""
import logging
from typing import Optional
from app.scrapers.base import BaseScraper

logger = logging.getLogger("price_tracker.scraper.generic")


class GenericScraper(BaseScraper):
    store_name = "generic"

    # No hardcoded selectors for generic sites
    css_selectors = []

    # Broad regex fallbacks for common price patterns
    regex_patterns = [
        r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})',
        r'\"price\"\\s*:\\s*\"?(\\d+[\\.,]?\\d*)\"?',
        r'\"lowPrice\"\\s*:\\s*\"?(\\d+[\\.,]?\\d*)\"?',
    ]

    async def extract_price(self, url: str) -> Optional[float]:
        """
        Extract price from URL using cascade extraction only.
        Custom selector is handled by BaseScraper.scrape() before this is called.
        """
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            # Run cascade (JSON-LD -> meta -> regex, no CSS selectors for generic)
            result = await self.cascade_extract(page, wait_ms=0)
            if result and result.price:
                logger.info(f"[generic] Cascade ({result.method}) matched: R$ {result.price:,.2f}")
                return result.price

            logger.warning(f"[generic] All extraction methods failed for {url}")
            return None
        finally:
            await page.close()
            await page.context.close()
