"""
Element Picker API endpoints.
Loads a page in Playwright, takes a screenshot, extracts visible elements
with their CSS selectors, and lets the user pick the price element.
"""
import asyncio
import base64
import logging
import random
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from app.database import get_db
from app.scrapers.registry import validate_url, detect_store

logger = logging.getLogger("price_tracker.picker")
router = APIRouter(prefix="/picker")
templates = Jinja2Templates(directory="app/templates")

# Rate limiting: simple in-memory tracker
_picker_requests: dict[str, float] = {}
PICKER_COOLDOWN_SECONDS = 5


class PickerLoadRequest(BaseModel):
    url: str
    store: str = "generic"


class PickerConfirmRequest(BaseModel):
    link_id: int
    selector: str
    preview_text: str = ""


class PickerClearRequest(BaseModel):
    link_id: int


async def _load_page_and_extract(url: str) -> dict:
    """
    Load a URL in Playwright, take a screenshot, and extract all visible
    text elements with their bounding boxes and CSS selectors.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            ]),
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        page = await context.new_page()

        # Apply stealth if available
        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except Exception:
            pass

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)  # Let dynamic content render

            # Take viewport screenshot
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

            # Extract visible elements with text and bounding boxes
            elements = await page.evaluate("""
                () => {
                    const results = [];
                    const seen = new Set();
                    let idx = 0;

                    // Generate a robust CSS selector for an element
                    function generateSelector(el) {
                        // 1. Try ID
                        if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) {
                            return '#' + CSS.escape(el.id);
                        }

                        // 2. Try data-testid or data-cy
                        for (const attr of ['data-testid', 'data-cy', 'data-test', 'data-id']) {
                            const val = el.getAttribute(attr);
                            if (val) {
                                const sel = `[${attr}="${val}"]`;
                                if (document.querySelectorAll(sel).length === 1) return sel;
                            }
                        }

                        // 3. Try unique class combination
                        if (el.classList.length > 0) {
                            const classes = Array.from(el.classList)
                                .filter(c => !c.match(/^[0-9]/) && c.length < 50)  // skip hashed classes
                                .slice(0, 3);
                            if (classes.length > 0) {
                                const sel = el.tagName.toLowerCase() + '.' + classes.map(c => CSS.escape(c)).join('.');
                                try {
                                    if (document.querySelectorAll(sel).length === 1) return sel;
                                } catch(e) {}
                            }
                        }

                        // 4. Build nth-child chain (max 4 levels)
                        const parts = [];
                        let current = el;
                        for (let i = 0; i < 4 && current && current !== document.body; i++) {
                            let tag = current.tagName.toLowerCase();
                            const parent = current.parentElement;
                            if (parent) {
                                const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
                                if (siblings.length > 1) {
                                    const nth = siblings.indexOf(current) + 1;
                                    tag += `:nth-of-type(${nth})`;
                                }
                            }
                            parts.unshift(tag);
                            // Stop if we have a unique selector
                            const candidate = parts.join(' > ');
                            try {
                                if (document.querySelectorAll(candidate).length === 1) return candidate;
                            } catch(e) {}
                            current = current.parentElement;
                        }
                        return parts.join(' > ');
                    }

                    // Walk all elements in the viewport
                    const allEls = document.querySelectorAll('*');
                    for (const el of allEls) {
                        // Skip invisible elements
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 || rect.height === 0) continue;
                        if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
                        if (rect.right < 0 || rect.left > window.innerWidth) continue;

                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

                        // Get text content (direct text only, not children's text)
                        const directText = Array.from(el.childNodes)
                            .filter(n => n.nodeType === 3)
                            .map(n => n.textContent.trim())
                            .join(' ')
                            .trim();

                        // Also get innerText for elements that have it
                        const innerText = (el.innerText || '').trim();

                        // Only include elements that have some text
                        if (!directText && !innerText) continue;

                        // Skip very long text (likely paragraphs, not prices)
                        const text = directText || innerText;
                        if (text.length > 200) continue;

                        // Create a key to deduplicate overlapping elements
                        const key = `${Math.round(rect.top)}_${Math.round(rect.left)}_${Math.round(rect.width)}_${Math.round(rect.height)}`;
                        if (seen.has(key)) continue;
                        seen.add(key);

                        const selector = generateSelector(el);

                        results.push({
                            index: idx++,
                            bbox: {
                                x: Math.round(rect.left),
                                y: Math.round(rect.top),
                                w: Math.round(rect.width),
                                h: Math.round(rect.height),
                            },
                            text: text.substring(0, 100),
                            directText: (directText || '').substring(0, 100),
                            tag: el.tagName.toLowerCase(),
                            selector: selector,
                            classes: Array.from(el.classList).slice(0, 5).join(' '),
                        });

                        // Cap at 500 elements to keep response manageable
                        if (results.length >= 500) break;
                    }

                    return results;
                }
            """)

            # Get page title
            title = await page.title()

            return {
                "screenshot": screenshot_b64,
                "elements": elements,
                "title": title,
                "url": url,
                "viewport": {"width": 1280, "height": 900},
            }

        finally:
            await page.close()
            await context.close()
            await browser.close()


@router.post("/load")
async def picker_load(req: PickerLoadRequest):
    """
    Load a URL and return screenshot + element map for the picker UI.
    """
    # SSRF validation
    store = req.store or detect_store(req.url)
    try:
        url = validate_url(req.url, store)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Rate limiting (simple per-URL cooldown)
    import time
    now = time.time()
    last = _picker_requests.get(url, 0)
    if now - last < PICKER_COOLDOWN_SECONDS:
        raise HTTPException(429, f"Please wait {PICKER_COOLDOWN_SECONDS}s before reloading.")
    _picker_requests[url] = now

    try:
        result = await _load_page_and_extract(url)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Picker load failed for {url}: {e}")
        raise HTTPException(500, f"Failed to load page: {str(e)[:200]}")


@router.post("/confirm")
async def picker_confirm(req: PickerConfirmRequest):
    """
    Save the user-picked CSS selector for a product link.
    """
    # Validate selector: must be a non-empty CSS selector string
    selector = req.selector.strip()
    if not selector:
        raise HTTPException(400, "Selector cannot be empty.")
    if len(selector) > 500:
        raise HTTPException(400, "Selector too long (max 500 chars).")

    # Basic CSS selector validation — block obviously dangerous patterns
    dangerous = ['<', '>', 'javascript:', 'on', 'eval(', 'script']
    for d in dangerous:
        if d in selector.lower():
            raise HTTPException(400, f"Invalid selector: contains '{d}'.")

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM product_links WHERE id = ?", (req.link_id,)
        )
        if not await cursor.fetchone():
            raise HTTPException(404, "Link not found.")

        await db.execute(
            "UPDATE product_links SET custom_selector = ? WHERE id = ?",
            (selector, req.link_id),
        )
        await db.commit()
        logger.info(f"Saved custom selector for link {req.link_id}: {selector}")
        return JSONResponse({"ok": True, "selector": selector})
    finally:
        await db.close()


@router.post("/clear")
async def picker_clear(req: PickerClearRequest):
    """
    Remove the custom selector for a product link (revert to auto-detection).
    """
    db = await get_db()
    try:
        await db.execute(
            "UPDATE product_links SET custom_selector = NULL WHERE id = ?",
            (req.link_id,),
        )
        await db.commit()
        logger.info(f"Cleared custom selector for link {req.link_id}")
        return JSONResponse({"ok": True})
    finally:
        await db.close()


@router.get("/{product_id}/{link_id}", response_class=HTMLResponse)
async def picker_page(request: Request, product_id: int, link_id: int):
    """
    Serve the element picker page for a specific link.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM product_links WHERE id = ? AND product_id = ?",
            (link_id, product_id),
        )
        link = await cursor.fetchone()
        if not link:
            raise HTTPException(404, "Link not found.")
        link = dict(link)

        cursor2 = await db.execute(
            "SELECT name FROM products WHERE id = ?", (product_id,)
        )
        product = await cursor2.fetchone()
        product_name = product["name"] if product else "Unknown"
    finally:
        await db.close()

    return templates.TemplateResponse("picker.html", {
        "request": request,
        "product_id": product_id,
        "link": link,
        "product_name": product_name,
    })
