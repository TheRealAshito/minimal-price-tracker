import re
import random
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]


class BaseScraper(ABC):
    store_name: str

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
            pass

        return page

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @abstractmethod
    async def extract_price(self, url: str) -> Optional[float]:
        """Extract price from URL. Returns price as float or None if failed."""
        pass

    async def scrape(self, url: str) -> tuple[Optional[float], Optional[str]]:
        """Main scrape method. Returns (price, error_message)."""
        try:
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
        cleaned = text.replace("R$", "").replace("r$", "").strip()
        # Remove thousands separator (.) and convert decimal comma (,) to dot
        cleaned = re.sub(r"\.(?=\d{3})", "", cleaned)
        cleaned = cleaned.replace(",", ".")
        # Extract first number
        match = re.search(r"(\d+\.?\d*)", cleaned)
        if match:
            return float(match.group(1))
        return None
