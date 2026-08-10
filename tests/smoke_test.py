#!/usr/bin/env python3
"""
Smoke test for minimal-price-tracker.
Run: cd /home/agentic_ia/minimal-price-tracker && .venv/bin/python3 tests/smoke_test.py
"""
import sys, os, json

# Setup paths
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

TEST_DB = os.path.join(ROOT, "tests", "test.db")
os.environ["DATABASE_URL"] = TEST_DB

import app.config as cfg
from pathlib import Path
cfg.DB_PATH = Path(TEST_DB)
import app.database as db_mod
db_mod.DB_PATH = Path(TEST_DB)

# Cleanup old test DB
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
import aiosqlite

passed = 0
failed = 0

def ok(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


async def test():
    await db_mod.init_db()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # ── Core routes ────────────────────────────────────────
        for path in ["/", "/products", "/alerts", "/settings", "/logs", "/api/dashboard/summary"]:
            r = await c.get(path)
            ok(f"GET {path}", r.status_code == 200)

        # ── Debug endpoints ────────────────────────────────────
        r = await c.get("/debug/errors")
        ok("GET /debug/errors", r.status_code == 200 and "errors" in r.json())

        r = await c.get("/debug/stats")
        ok("GET /debug/stats", r.status_code == 200 and "log_stats" in r.json())

        # ── Product CRUD ───────────────────────────────────────
        r = await c.post("/products/add", data={"name": "Test GPU"})
        ok("create product", r.status_code == 303)

        r = await c.get("/products/1")
        ok("get product detail", r.status_code == 200 and "Test GPU" in r.text)

        # ── Add link ───────────────────────────────────────────
        r = await c.post("/products/1/add-link", data={"url": "https://example.com/gpu", "store": "generic"})
        ok("add generic link", r.status_code == 303)

        # ── Rename ─────────────────────────────────────────────
        r = await c.post("/products/1/rename", data={"name": "RTX 4070 Super"})
        ok("rename product", r.status_code == 303)

        async with aiosqlite.connect(TEST_DB) as conn:
            cur = await conn.execute("SELECT name FROM products WHERE id=1")
            ok("rename persisted", (await cur.fetchone())[0] == "RTX 4070 Super")

        # ── Picker ─────────────────────────────────────────────
        r = await c.get("/picker/1/1")
        ok("picker page", r.status_code == 200 and "session/start" in r.text)

        r = await c.post("/picker/confirm", json={
            "link_id": 1, "selector": "div > span.price",
            "preview_text": "R$ 1.299,90",
            "pre_actions": [{"type": "click", "x": 100, "y": 200}, {"type": "wait", "ms": 3000}],
        })
        ok("confirm selector with > and pre_actions", r.status_code == 200 and r.json().get("pre_actions_count") == 2)

        async with aiosqlite.connect(TEST_DB) as conn:
            cur = await conn.execute("SELECT custom_selector, pre_actions FROM product_links WHERE id=1")
            row = await cur.fetchone()
            ok("selector saved", row[0] == "div > span.price")
            ok("pre_actions saved", len(json.loads(row[1])) == 2)

        # ── Selector validation ────────────────────────────────
        r = await c.post("/picker/confirm", json={"link_id": 1, "selector": "<script>x</script>"})
        ok("XSS blocked", r.status_code == 400)

        r = await c.post("/picker/confirm", json={"link_id": 1, "selector": ""})
        ok("empty blocked", r.status_code == 400)

        r = await c.post("/picker/confirm", json={"link_id": 1, "selector": "a" * 501})
        ok("too long blocked", r.status_code == 400)

        # ── Clear ──────────────────────────────────────────────
        r = await c.post("/picker/clear", json={"link_id": 1})
        ok("clear selector", r.status_code == 200)

        async with aiosqlite.connect(TEST_DB) as conn:
            cur = await conn.execute("SELECT custom_selector, pre_actions FROM product_links WHERE id=1")
            row = await cur.fetchone()
            ok("cleared in DB", row[0] is None and row[1] is None)

        # ── NULL safety ────────────────────────────────────────
        async with aiosqlite.connect(TEST_DB) as conn:
            await conn.execute("UPDATE product_links SET consecutive_failures = NULL WHERE id=1")
            await conn.commit()

        r = await c.get("/products/1")
        ok("NULL consecutive_failures safe", r.status_code == 200)

        r = await c.get("/products")
        ok("products list with NULL", r.status_code == 200)

        # ── DB migration ───────────────────────────────────────
        async with aiosqlite.connect(TEST_DB) as conn:
            cur = await conn.execute("PRAGMA table_info(product_links)")
            cols = [r[1] for r in await cur.fetchall()]
            ok("custom_selector column", "custom_selector" in cols)
            ok("pre_actions column", "pre_actions" in cols)

        # ── Date format setting ────────────────────────────────
        async with aiosqlite.connect(TEST_DB) as conn:
            cur = await conn.execute("SELECT value FROM settings WHERE key='date_format'")
            row = await cur.fetchone()
            ok("date_format default is DD/MM/YYYY", row and row[0] == "DD/MM/YYYY")

        r = await c.post("/settings/date-format", data={"date_format": "DD-MM-YYYY"}, follow_redirects=False)
        ok("update date format", r.status_code == 303)

        async with aiosqlite.connect(TEST_DB) as conn:
            cur = await conn.execute("SELECT value FROM settings WHERE key='date_format'")
            row = await cur.fetchone()
            ok("date_format persisted", row and row[0] == "DD-MM-YYYY")

        # Test format_date function
        from app.date_format import format_date, format_datetime
        ok("format_date DD/MM/YYYY", format_date("2026-07-31 14:30:00", "DD/MM/YYYY") == "31/07/2026")
        ok("format_date MM/DD/YYYY", format_date("2026-07-31 14:30:00", "MM/DD/YYYY") == "07/31/2026")
        ok("format_date DD-MM-YYYY", format_date("2026-07-31 14:30:00", "DD-MM-YYYY") == "31-07-2026")
        ok("format_date YYYY-MM-DD", format_date("2026-07-31 14:30:00", "YYYY-MM-DD") == "2026-07-31")
        ok("format_date PT month", "Jul" in format_date("2026-07-31 14:30:00", "DD/Mon/AAAA (PT)"))
        ok("format_datetime has time", "14:30" in format_datetime("2026-07-31 14:30:00", "DD/MM/YYYY"))
        ok("format_date None safe", format_date(None) == "")
        ok("format_date empty safe", format_date("") == "")

    # Cleanup
    os.remove(TEST_DB)

    print(f"\n{'='*50}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*50}")
    return failed


if __name__ == "__main__":
    failures = asyncio.run(test())
    sys.exit(1 if failures else 0)
