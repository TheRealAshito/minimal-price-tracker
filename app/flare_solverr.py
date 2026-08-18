"""
FlareSolverr client for Cloudflare bypass.
Sends URLs to FlareSolverr, gets back rendered HTML + cookies.
Caches solutions per domain to avoid re-solving for the same site.

FlareSolverr API: POST http://host:8191/v1
Body: {"cmd": "request.get", "url": "...", "maxTimeout": 60000}
Returns: {"solution": {"response": "<html>...", "cookies": [...], "user_agent": "..."}}
"""
import asyncio
import logging
import time
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("price_tracker.flaresolverr")

# Cache: domain -> {html, cookies, user_agent, solved_at}
_solution_cache: dict[str, dict] = {}
CACHE_TTL = 25 * 60  # 25 minutes (cf_clearance lasts ~30 min)


def _get_flare_url() -> Optional[str]:
    """Get FlareSolverr URL from settings."""
    try:
        from app.database import get_db
        # Can't use async here, read from config instead
        from app.config import settings
        return getattr(settings, 'flaresolverr_url', '').strip() or None
    except Exception:
        return None


async def solve(url: str, max_timeout: int = 60000) -> Optional[dict]:
    """
    Send a URL to FlareSolverr and get the rendered HTML + cookies.
    Returns dict with {html, cookies, user_agent} or None on failure.
    Caches per domain for CACHE_TTL seconds.
    """
    from app.database import get_db

    # Get FlareSolverr URL from DB settings
    flare_url = None
    try:
        db = await get_db()
        try:
            cursor = await db.execute("SELECT value FROM settings WHERE key = 'flaresolverr_url'")
            row = await cursor.fetchone()
            if row and row["value"]:
                flare_url = row["value"].strip()
        finally:
            await db.close()
    except Exception:
        pass

    if not flare_url:
        return None

    # Check cache
    domain = urlparse(url).hostname or ""
    cached = _solution_cache.get(domain)
    if cached and (time.time() - cached["solved_at"]) < CACHE_TTL:
        logger.debug(f"[FlareSolverr] Cache hit for {domain}")
        return cached

    # Call FlareSolverr
    endpoint = f"{flare_url.rstrip('/')}/v1"
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": max_timeout,
    }

    try:
        logger.info(f"[FlareSolverr] Solving {url}...")
        async with httpx.AsyncClient(timeout=max_timeout / 1000 + 30) as client:
            resp = await client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "ok":
            logger.warning(f"[FlareSolverr] Failed: {data.get('message', 'unknown error')}")
            return None

        solution = data.get("solution", {})
        html = solution.get("response", "")
        cookies = solution.get("cookies", [])
        user_agent = solution.get("user_agent", "")

        if not html:
            logger.warning(f"[FlareSolverr] Empty response for {url}")
            return None

        result = {
            "html": html,
            "cookies": cookies,
            "user_agent": user_agent,
            "solved_at": time.time(),
            "status": solution.get("status", 0),
        }

        # Cache it
        _solution_cache[domain] = result
        logger.info(f"[FlareSolverr] Solved {domain} ({len(html)} bytes, {len(cookies)} cookies)")
        return result

    except httpx.ConnectError:
        logger.warning(f"[FlareSolverr] Cannot connect to {flare_url}. Is FlareSolverr running?")
        return None
    except httpx.TimeoutException:
        logger.warning(f"[FlareSolverr] Timeout solving {url} (>{max_timeout}ms)")
        return None
    except Exception as e:
        logger.warning(f"[FlareSolverr] Error: {e}")
        return None


async def inject_cookies(page, cookies: list):
    """Inject FlareSolverr cookies into a Playwright page's context."""
    if not cookies:
        return
    try:
        # Convert FlareSolverr cookie format to Playwright format
        pw_cookies = []
        for c in cookies:
            cookie = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ""),
                "path": c.get("path", "/"),
            }
            # Playwright requires either url or domain+path
            if cookie["domain"]:
                pw_cookies.append(cookie)

        if pw_cookies:
            await page.context.add_cookies(pw_cookies)
            logger.debug(f"[FlareSolverr] Injected {len(pw_cookies)} cookies")
    except Exception as e:
        logger.debug(f"[FlareSolverr] Cookie injection failed: {e}")


def clear_cache():
    """Clear the solution cache (e.g. when settings change)."""
    _solution_cache.clear()
