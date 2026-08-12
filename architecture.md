# Minimal Price Tracker - Architecture

## Overview

A local-first price tracker that scrapes Brazilian e-commerce sites using Playwright, stores price history in SQLite, and provides a web dashboard for analysis and alerts. Optimized for low RAM usage (~150MB idle, ~400MB during scrape cycles).

## System Architecture
```
+---------------------------------------------------------+
|                   Docker Container                       |
|                                                          |
|  +----------------------------------------------------+ |
|  |              FastAPI Application                    | |
|  |                                                     | |
|  |  +-----------+  +------------+  +--------------+  | |
|  |  |  Jinja2   |  | APScheduler|  |  BrowserMgr   |  | |
|  |  | Templates |  | (interval) |  |  (on-demand)  |  | |
|  |  +-----+-----+  +-----+------+  +------+-------+  | |
|  |        |              |                |           | |
|  |  +-----+--------------+----------------+--------+  | |
|  |  |            Service Layer                      |  | |
|  |  |  - PriceService  (stats, history, comparison) |  | |
|  |  |  - AlertService  (threshold evaluation)       |  | |
|  |  |  - BackupService (export/import/prune)        |  | |
|  |  +---------------------+------------------------+  | |
|  |                        |                             | |
|  |  +---------------------+------------------------+  | |
|  |  |              SQLite (WAL mode)                 |  | |
|  |  |  Tables: products, price_history, settings     |  | |
|  |  +-----------------------------------------------+  | |
|  +----------------------------------------------------+ |
|                                                          |
|  Port: 8035 (0.0.0.0 for NPM)                           |
+---------------------------------------------------------+
         |
         v
  +--------------+
  |  Scraping     |
  |  Targets:     |
  |  - KaBum      |
  |  - Shopee     |
  |  - Amazon BR  |
  |  - AliExpress |
  |  - Terabyte   |
  |  - Generic    |
  +--------------+
```

## RAM Optimization

The app is designed for minimal memory footprint:

1. **Shared Browser Instance**: A single Chromium instance (`BrowserManager`) is shared across all scrapers during a scrape cycle. No redundant browser contexts.

2. **Shutdown After Cycle**: Chromium is completely shut down after each scrape cycle finishes, freeing ~300MB of RAM between cycles.

3. **Lazy Startup**: The scheduler does NOT run the first scrape immediately on container start. Chromium stays dormant until the first interval fires. Trigger manual scrapes from the UI if needed immediately.

4. **Memory-Reduced Chromium**: Flags disable GPU, extensions, background networking, sync, translate, and metrics.

5. **Persistent Profile**: Cookie/session data persists in `data/browser-profile/` across browser restarts (Cloudflare bypass, login sessions).

**Expected RAM usage:**
- Idle (between scrapes): ~150MB (Python + FastAPI + SQLite)
- During scrape cycle: ~400MB (Chromium active)
- After cycle completes: back to ~150MB

## Data Flow

1. **Add Product**: User submits URL -> store auto-detected -> product saved to SQLite
2. **Scrape Cycle** (every 6h):
   - APScheduler triggers `run_all_scrapes()`
   - `BrowserManager` starts a single Chromium instance
   - For each active product, a new page is created from the shared context
   - Store-specific scraper extracts price using CSS selectors + regex fallback
   - Price recorded in `price_history` table
   - Alert thresholds evaluated -> logged if triggered
   - On failure: failure count incremented -> auto-disable after 10
   - After all links scraped: Chromium shut down completely
3. **Dashboard**: Reads from SQLite, renders charts via Chart.js
4. **Prune**: Old data (>365 days) deleted after each scrape cycle

## Database Schema

```sql
products (logical grouping -- one per tracked item)
  id              INTEGER PRIMARY KEY
  name            TEXT NOT NULL
  alert_price_abs REAL          -- absolute price threshold
  alert_price_pct REAL          -- percentage drop threshold
  alert_below_mean INTEGER      -- boolean: alert when below mean
  active          INTEGER       -- boolean: tracking enabled
  created_at      TIMESTAMP

product_links (individual URLs per product)
  id              INTEGER PRIMARY KEY
  product_id      INTEGER -> products.id
  url             TEXT NOT NULL UNIQUE
  store           TEXT CHECK(store IN ('kabum','shopee','amazon','aliexpress','terabyte','generic'))
  custom_selector TEXT          -- user-picked CSS selector (nullable)
  pre_actions     TEXT          -- JSON array of recorded pre-scrape actions (nullable)
  consecutive_failures INTEGER  -- failure counter per link
  created_at      TIMESTAMP

price_history
  id          INTEGER PRIMARY KEY
  link_id     INTEGER -> product_links.id
  price       REAL              -- null on failure
  status      TEXT CHECK(status IN ('success','failed','blocked'))
  error_message TEXT
  scraped_at  TIMESTAMP

settings
  key         TEXT PRIMARY KEY
  value       TEXT
```

One product can have multiple links (e.g., same GPU on KaBum + Amazon + AliExpress).
Stats are computed across all links for a product.

## Scraper Strategy

- **Playwright Chromium** headless with stealth patches
- **Shared BrowserManager**: single instance per scrape cycle, shut down after
- **Rotating user-agents** from a pool of 5
- **Random delays** (2-8s) between requests
- **Multi-selector fallback**: tries CSS selectors, then regex on page source
- **JSON-LD extraction**: looks for structured data as last resort
- Per-store modules: fixing one store doesn't affect others
- **Custom selector override**: user-picked CSS selector takes priority over all auto-detection
- **Generic scraper**: any website via element picker + custom selector

## Element Picker (Universal Price Selector)

The element picker lets users visually select the price element on any webpage:

1. User clicks "Pick Element" on a product link
2. Backend loads the page in Playwright (headless Chromium)
3. Takes a viewport screenshot + extracts all visible text elements with bounding boxes
4. Frontend renders the screenshot with clickable overlays
5. User clicks on the price -> system generates a CSS selector
6. Preview shows the extracted text for verification
7. User confirms -> selector saved to `product_links.custom_selector`

**Scrape priority per link:**
1. Custom selector (if set) -> tried first (with pre_actions replay)
2. Store-specific cascade -> CSS -> JSON-LD -> meta -> regex
3. Failure recorded if both fail

**Pre-actions (recorded browser interactions):**
- Stored as JSON array in `product_links.pre_actions`
- Supported action types: click (x,y), scroll (direction, amount), wait (ms), type (text), goto (url)
- Auto-recorded during picker navigation
- Replayed in order before each scrape attempt
- Used for: dismissing cookie banners, selecting language, scrolling past overlays

**Security:**
- SSRF protection: blocks private IPs, localhost, link-local
- Custom selector validation: pure CSS, no executable content
- Rate limiting on picker load endpoint
- Screenshots not persisted (in-memory only)

## File Structure

```
app/
+-- main.py           # FastAPI app, lifespan, router registration
+-- config.py         # Pydantic settings
+-- database.py       # SQLite connection, schema, init + migrations
+-- models.py         # Pydantic models
+-- scheduler.py      # APScheduler setup, scrape orchestration
+-- browser_manager.py # Shared Chromium instance (start/stop per cycle)
+-- date_format.py    # Date formatting utilities
+-- log_buffer.py     # In-memory log buffer for web UI
+-- templates_config.py # Jinja2 template config
+-- routers/
|   +-- dashboard.py  # Dashboard page
|   +-- products.py   # Product CRUD + detail
|   +-- alerts.py     # Alert history page
|   +-- settings.py   # Backup, restore, interval, date format
|   +-- api.py        # JSON endpoints for charts
|   +-- picker.py     # Element picker API (load, confirm, clear)
|   +-- logs.py       # Log viewer page
+-- scrapers/
|   +-- base.py       # BaseScraper (cascade extraction, BRL parser)
|   +-- kabum.py      # KaBum scraper
|   +-- shopee.py     # Shopee scraper
|   +-- amazon.py     # Amazon Brazil scraper
|   +-- aliexpress.py # AliExpress scraper
|   +-- terabyte.py   # Terabyte scraper
|   +-- generic.py    # Generic scraper (any website)
|   +-- registry.py   # Store detection + scraper factory + SSRF validation
+-- services/
|   +-- price_service.py   # Stats, history, comparison
|   +-- alert_service.py   # Threshold evaluation, failure handling
|   +-- backup_service.py  # Export, import, prune
+-- templates/        # Jinja2 HTML templates
|   +-- base.html
|   +-- dashboard.html
|   +-- products.html
|   +-- product_detail.html
|   +-- alerts.html
|   +-- settings.html
|   +-- logs.html
|   +-- picker.html   # Element picker UI (screenshot overlay)
+-- static/
    +-- js/charts.js  # Chart.js utilities
```
