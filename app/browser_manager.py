"""
Shared browser manager for all scrapers.
Starts Chromium once per scrape cycle, all scrapers share the same instance,
and shuts down completely after the cycle finishes to free ~300MB of RAM.

Persistent browser profile is kept for cookie/session persistence (Cloudflare, etc.)
"""
import asyncio
import logging
import random
from typing import Optional

logger = logging.getLogger("price_tracker.browser")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]

# Persistent browser profile directory — keeps cookies across sessions
BROWSER_PROFILE_DIR = None  # Lazy import to avoid circular deps


def _get_profile_dir():
    from pathlib import Path
    global BROWSER_PROFILE_DIR
    if BROWSER_PROFILE_DIR is None:
        BROWSER_PROFILE_DIR = Path("data/browser-profile")
    return BROWSER_PROFILE_DIR


class BrowserManager:
    """Singleton that manages a shared Chromium instance."""

    def __init__(self):
        self._playwright = None
        self._context = None
        self._lock = asyncio.Lock()

    async def get_context(self):
        """Get or create the shared browser context."""
        async with self._lock:
            if self._context is None:
                from playwright.async_api import async_playwright

                profile_dir = _get_profile_dir()
                profile_dir.mkdir(parents=True, exist_ok=True)

                logger.info("Starting Chromium (shared instance)...")
                self._playwright = await async_playwright().start()
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-extensions",
                        "--disable-background-networking",
                        "--disable-sync",
                        "--disable-translate",
                        "--metrics-recording-only",
                        "--no-first-run",
                    ],
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1920, "height": 1080},
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )
                logger.info("Chromium started.")
            return self._context

    async def new_page(self):
        """Create a new page from the shared browser context."""
        context = await self.get_context()
        page = await context.new_page()

        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except Exception:
            pass

        return page

    async def close_page(self, page):
        """Close a page without destroying the shared context."""
        try:
            await page.close()
        except Exception:
            pass

    async def shutdown(self):
        """Shut down the browser completely to free memory."""
        async with self._lock:
            if self._context:
                try:
                    await self._context.close()
                except Exception as e:
                    logger.debug(f"Error closing context: {e}")
                self._context = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.debug(f"Error stopping playwright: {e}")
                self._playwright = None
            logger.info("Chromium shut down. Memory freed.")

    @property
    def is_running(self) -> bool:
        return self._context is not None


# Global singleton
browser_manager = BrowserManager()
