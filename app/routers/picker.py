"""
Interactive Element Picker with session-based Playwright browser.
Users can navigate, scroll, click through pages while actions are auto-recorded
for replay during scrape cycles.
"""
import asyncio
import base64
import json
import logging
import random
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from app.database import get_db
from app.scrapers.registry import validate_url, detect_store

logger = logging.getLogger("price_tracker.picker")
router = APIRouter(prefix="/picker")
from app.templates_config import templates

# ── Session management ────────────────────────────────────────────
_sessions: dict[str, dict] = {}
SESSION_TTL = 600  # 10 minutes


def _cleanup_sessions():
    """Remove expired sessions."""
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now - s["created"] > SESSION_TTL]
    for sid in expired:
        s = _sessions.pop(sid, None)
        if s:
            try:
                asyncio.get_event_loop().create_task(_close_session(s))
            except Exception:
                pass


async def _close_session(session: dict):
    """Close Playwright resources for a session.
    Closes the page and context (cookies are saved to disk automatically).
    """
    try:
        if session.get("page"):
            await session["page"].close()
        if session.get("context"):
            await session["context"].close()
        if session.get("playwright"):
            await session["playwright"].stop()
    except Exception as e:
        logger.debug(f"Error closing session: {e}")


# ── JS for element extraction (reused across requests) ────────────
ELEMENT_EXTRACT_JS = """
() => {
    const results = [];
    const seen = new Set();
    let idx = 0;

    function generateSelector(el) {
        if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1)
            return '#' + CSS.escape(el.id);
        for (const attr of ['data-testid', 'data-cy', 'data-test', 'data-id']) {
            const val = el.getAttribute(attr);
            if (val) {
                const sel = `[${attr}="${val}"]`;
                if (document.querySelectorAll(sel).length === 1) return sel;
            }
        }
        if (el.classList.length > 0) {
            const classes = Array.from(el.classList).filter(c => !c.match(/^[0-9]/) && c.length < 50).slice(0, 3);
            if (classes.length > 0) {
                const sel = el.tagName.toLowerCase() + '.' + classes.map(c => CSS.escape(c)).join('.');
                try { if (document.querySelectorAll(sel).length === 1) return sel; } catch(e) {}
            }
        }
        const parts = [];
        let current = el;
        for (let i = 0; i < 4 && current && current !== document.body; i++) {
            let tag = current.tagName.toLowerCase();
            const parent = current.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
                if (siblings.length > 1) tag += `:nth-of-type(${siblings.indexOf(current) + 1})`;
            }
            parts.unshift(tag);
            const candidate = parts.join(' > ');
            try { if (document.querySelectorAll(candidate).length === 1) return candidate; } catch(e) {}
            current = current.parentElement;
        }
        return parts.join(' > ');
    }

    const allEls = document.querySelectorAll('*');
    for (const el of allEls) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
        if (rect.right < 0 || rect.left > window.innerWidth) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
        const directText = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
        const innerText = (el.innerText || '').trim();
        const text = directText || innerText;
        if (!text || text.length > 200) continue;
        const key = `${Math.round(rect.top)}_${Math.round(rect.left)}_${Math.round(rect.width)}_${Math.round(rect.height)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        results.push({
            index: idx++,
            bbox: { x: Math.round(rect.left), y: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height) },
            text: text.substring(0, 100),
            directText: (directText || '').substring(0, 100),
            tag: el.tagName.toLowerCase(),
            selector: generateSelector(el),
            classes: Array.from(el.classList).slice(0, 5).join(' '),
        });
        if (results.length >= 500) break;
    }
    return results;
}
"""


async def _capture(session: dict) -> dict:
    """Take screenshot + extract elements from current page state."""
    page = session["page"]
    screenshot_bytes = await page.screenshot(type="png", full_page=False)
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
    elements = await page.evaluate(ELEMENT_EXTRACT_JS)
    title = await page.title()
    url = page.url
    return {
        "screenshot": screenshot_b64,
        "elements": elements,
        "title": title,
        "url": url,
    }


# ── Request models ────────────────────────────────────────────────

class SessionStartRequest(BaseModel):
    url: str
    store: str = "generic"


class SessionActionRequest(BaseModel):
    session_id: str
    type: str  # click, scroll, wait, type, goto
    x: Optional[int] = None
    y: Optional[int] = None
    direction: Optional[str] = None  # up, down
    amount: Optional[int] = None  # scroll ticks
    ms: Optional[int] = None  # wait ms
    text: Optional[str] = None  # text to type
    url: Optional[str] = None  # for goto


class SessionPickRequest(BaseModel):
    session_id: str
    x: int
    y: int


class SessionConfirmRequest(BaseModel):
    session_id: str
    link_id: int


class SessionCancelRequest(BaseModel):
    session_id: str


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("/session/start")
async def session_start(req: SessionStartRequest):
    """Start an interactive picker session."""
    _cleanup_sessions()

    store = req.store or detect_store(req.url)
    try:
        url = validate_url(req.url, store)
    except ValueError as e:
        raise HTTPException(400, str(e))

    from playwright.async_api import async_playwright
    from app.scrapers.base import BROWSER_PROFILE_DIR

    pw = await async_playwright().start()

    # Ensure profile directory exists
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_PROFILE_DIR),
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-sandbox"],
        user_agent=random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ]),
        viewport={"width": 1280, "height": 900},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
    )
    page = await context.new_page()
    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except Exception:
        pass

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)
    except Exception as e:
        logger.error(f"Picker session failed to load {url}: {e}", exc_info=True)
        await context.close()
        await pw.stop()
        raise HTTPException(500, f"Failed to load page: {str(e)[:200]}")

    session_id = str(uuid.uuid4())[:8]
    session = {
        "id": session_id,
        "playwright": pw,
        "browser": None,
        "context": context,
        "page": page,
        "url": url,
        "recorded_actions": [],
        "created": time.time(),
    }
    _sessions[session_id] = session

    capture = await _capture(session)
    return JSONResponse({
        "session_id": session_id,
        "recorded_actions": [],
        **capture,
    })


@router.post("/session/action")
async def session_action(req: SessionActionRequest):
    """Execute an action in the picker session (click, scroll, wait, type, goto)."""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session expired or not found. Start a new one.")

    page = session["page"]

    try:
        if req.type == "click":
            if req.x is None or req.y is None:
                raise HTTPException(400, "click requires x and y")
            await page.mouse.click(req.x, req.y)
            await page.wait_for_timeout(2000)
            session["recorded_actions"].append({"type": "click", "x": req.x, "y": req.y})

        elif req.type == "scroll":
            direction = req.direction or "down"
            amount = req.amount or 3
            for _ in range(amount):
                await page.mouse.wheel(0, 300 if direction == "down" else -300)
                await page.wait_for_timeout(200)
            await page.wait_for_timeout(1000)
            session["recorded_actions"].append({"type": "scroll", "direction": direction, "amount": amount})

        elif req.type == "wait":
            ms = req.ms or 3000
            await page.wait_for_timeout(ms)
            session["recorded_actions"].append({"type": "wait", "ms": ms})

        elif req.type == "type":
            if not req.text:
                raise HTTPException(400, "type requires text")
            await page.keyboard.type(req.text, delay=50)
            session["recorded_actions"].append({"type": "type", "text": req.text})

        elif req.type == "goto":
            if not req.url:
                raise HTTPException(400, "goto requires url")
            await page.goto(req.url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            session["recorded_actions"].append({"type": "goto", "url": req.url})

        else:
            raise HTTPException(400, f"Unknown action type: {req.type}")

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Action {req.type} failed: {e}", exc_info=True)
        # Don't record failed actions

    capture = await _capture(session)
    return JSONResponse({
        "recorded_actions": session["recorded_actions"],
        **capture,
    })


@router.post("/session/undo")
async def session_undo(req: SessionCancelRequest):
    """Undo the last recorded action by replaying all actions except the last one."""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session expired or not found.")
    if not session["recorded_actions"]:
        raise HTTPException(400, "No actions to undo.")

    # Remove last action
    session["recorded_actions"].pop()

    # Reload page and replay remaining actions
    page = session["page"]
    try:
        await page.goto(session["url"], wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        for action in session["recorded_actions"]:
            if action["type"] == "click":
                await page.mouse.click(action["x"], action["y"])
                await page.wait_for_timeout(2000)
            elif action["type"] == "scroll":
                for _ in range(action.get("amount", 3)):
                    await page.mouse.wheel(0, 300 if action.get("direction") == "down" else -300)
                    await page.wait_for_timeout(200)
                await page.wait_for_timeout(1000)
            elif action["type"] == "wait":
                await page.wait_for_timeout(action.get("ms", 3000))
            elif action["type"] == "type":
                await page.keyboard.type(action.get("text", ""), delay=50)
            elif action["type"] == "goto":
                await page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
    except Exception as e:
        logger.warning(f"Undo replay failed: {e}", exc_info=True)

    capture = await _capture(session)
    return JSONResponse({
        "recorded_actions": session["recorded_actions"],
        **capture,
    })


@router.post("/session/pick")
async def session_pick(req: SessionPickRequest):
    """Pick an element at (x, y) coordinates and return its CSS selector + preview."""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session expired or not found.")

    page = session["page"]

    # Use JavaScript to get the element at the coordinates and generate its selector
    result = await page.evaluate("""
        (args) => {
            const [x, y] = args;
            const el = document.elementFromPoint(x, y);
            if (!el) return null;

            function generateSelector(el) {
                if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1)
                    return '#' + CSS.escape(el.id);
                for (const attr of ['data-testid', 'data-cy', 'data-test', 'data-id']) {
                    const val = el.getAttribute(attr);
                    if (val) {
                        const sel = `[${attr}="${val}"]`;
                        if (document.querySelectorAll(sel).length === 1) return sel;
                    }
                }
                if (el.classList.length > 0) {
                    const classes = Array.from(el.classList).filter(c => !c.match(/^[0-9]/) && c.length < 50).slice(0, 3);
                    if (classes.length > 0) {
                        const sel = el.tagName.toLowerCase() + '.' + classes.map(c => CSS.escape(c)).join('.');
                        try { if (document.querySelectorAll(sel).length === 1) return sel; } catch(e) {}
                    }
                }
                const parts = [];
                let current = el;
                for (let i = 0; i < 4 && current && current !== document.body; i++) {
                    let tag = current.tagName.toLowerCase();
                    const parent = current.parentElement;
                    if (parent) {
                        const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
                        if (siblings.length > 1) tag += `:nth-of-type(${siblings.indexOf(current) + 1})`;
                    }
                    parts.unshift(tag);
                    const candidate = parts.join(' > ');
                    try { if (document.querySelectorAll(candidate).length === 1) return candidate; } catch(e) {}
                    current = current.parentElement;
                }
                return parts.join(' > ');
            }

            const innerText = (el.innerText || '').trim().substring(0, 100);
            const directText = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim().substring(0, 100);

            return {
                selector: generateSelector(el),
                text: innerText || directText,
                tag: el.tagName.toLowerCase(),
                classes: Array.from(el.classList).slice(0, 5).join(' '),
                bbox: (() => {
                    const r = el.getBoundingClientRect();
                    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
                })(),
            };
        }
    """, [req.x, req.y])

    if not result:
        raise HTTPException(400, "No element found at those coordinates.")

    return JSONResponse(result)


@router.post("/session/confirm")
async def session_confirm(req: SessionConfirmRequest):
    """Save the custom selector and recorded actions for a link."""
    session = _sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session expired or not found.")

    # The frontend sends selector and preview_text in the request
    # We need to get them from the last pick result
    # Actually, let's accept them from the frontend
    raise HTTPException(400, "Use /picker/confirm with selector and pre_actions directly.")


@router.post("/session/cancel")
async def session_cancel(req: SessionCancelRequest):
    """Cancel a picker session and clean up resources."""
    session = _sessions.pop(req.session_id, None)
    if session:
        await _close_session(session)
    return JSONResponse({"ok": True})


# ── Updated confirm/clear with pre_actions support ────────────────

class PickerConfirmRequest(BaseModel):
    link_id: int
    selector: str
    preview_text: str = ""
    pre_actions: list = []  # list of action dicts


class PickerClearRequest(BaseModel):
    link_id: int


@router.post("/confirm")
async def picker_confirm(req: PickerConfirmRequest):
    """Save the user-picked CSS selector and pre-actions for a product link."""
    selector = req.selector.strip()
    if not selector:
        raise HTTPException(400, "Selector cannot be empty.")
    if len(selector) > 500:
        raise HTTPException(400, "Selector too long (max 500 chars).")

    dangerous = ['<', 'javascript:', 'eval(', 'script']
    for d in dangerous:
        if d in selector.lower():
            raise HTTPException(400, f"Invalid selector: contains '{d}'.")

    # Validate and serialize pre_actions
    pre_actions_json = None
    if req.pre_actions:
        # Validate action types
        valid_types = {"click", "scroll", "wait", "type", "goto"}
        for action in req.pre_actions:
            if not isinstance(action, dict) or action.get("type") not in valid_types:
                raise HTTPException(400, f"Invalid action: {action}")
        pre_actions_json = json.dumps(req.pre_actions)

    db = await get_db()
    try:
        cursor = await db.execute("SELECT id FROM product_links WHERE id = ?", (req.link_id,))
        if not await cursor.fetchone():
            raise HTTPException(404, "Link not found.")

        await db.execute(
            "UPDATE product_links SET custom_selector = ?, pre_actions = ? WHERE id = ?",
            (selector, pre_actions_json, req.link_id),
        )
        await db.commit()
        logger.info(f"Saved custom selector for link {req.link_id}: {selector} ({len(req.pre_actions)} pre-actions)")
        return JSONResponse({"ok": True, "selector": selector, "pre_actions_count": len(req.pre_actions)})
    finally:
        await db.close()


@router.post("/clear")
async def picker_clear(req: PickerClearRequest):
    """Remove custom selector and pre-actions for a product link."""
    db = await get_db()
    try:
        await db.execute(
            "UPDATE product_links SET custom_selector = NULL, pre_actions = NULL WHERE id = ?",
            (req.link_id,),
        )
        await db.commit()
        logger.info(f"Cleared custom selector and pre-actions for link {req.link_id}")
        return JSONResponse({"ok": True})
    finally:
        await db.close()


# ── Page routes ───────────────────────────────────────────────────

@router.get("/{product_id}/{link_id}", response_class=HTMLResponse)
async def picker_page(request: Request, product_id: int, link_id: int):
    """Serve the interactive element picker page."""
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

        cursor2 = await db.execute("SELECT name FROM products WHERE id = ?", (product_id,))
        product = await cursor2.fetchone()
        product_name = product["name"] if product else "Unknown"
    finally:
        await db.close()

    # Parse existing pre_actions for display
    existing_actions = []
    if link.get("pre_actions"):
        try:
            existing_actions = json.loads(link["pre_actions"])
        except (json.JSONDecodeError, TypeError):
            pass

    return templates.TemplateResponse("picker.html", {
        "request": request,
        "product_id": product_id,
        "link": link,
        "product_name": product_name,
        "existing_actions": existing_actions,
    })
