# Minimal Price Tracker - Architecture

## Overview

A local-first price tracker that scrapes Brazilian e-commerce sites using Playwright, stores price history in SQLite, and provides a web dashboard for analysis and alerts.

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Docker Container                       │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │              FastAPI Application                    │ │
│  │                                                     │ │
│  │  ┌───────────┐  ┌────────────┐  ┌──────────────┐  │ │
│  │  │  Jinja2   │  │ APScheduler│  │  Playwright   │  │ │
│  │  │ Templates │  │ (6h cycle) │  │  (Chromium)   │  │ │
│  │  └─────┬─────┘  └─────┬──────┘  └──────┬───────┘  │ │
│  │        │              │                │           │ │
│  │  ┌─────┴──────────────┴────────────────┴────────┐  │ │
│  │  │            Service Layer                      │  │ │
│  │  │  - PriceService  (stats, history, comparison) │  │ │
│  │  │  - AlertService  (threshold evaluation)       │  │ │
│  │  │  - NtfyService   (push notifications)         │  │ │
│  │  │  - BackupService (export/import/prune)        │  │ │
│  │  └────────────────────┬──────────────────────────┘  │ │
│  │                       │                             │ │
│  │  ┌────────────────────┴──────────────────────────┐  │ │
│  │  │              SQLite (WAL mode)                 │  │ │
│  │  │  Tables: products, price_history, settings     │  │ │
│  │  └───────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  Port: 8035 (127.0.0.1 only)                            │
└─────────────────────────────────────────────────────────┘
         │
         ▼
  ┌──────────────┐     ┌──────────────────────┐
  │  Scraping     │     │  NTFY Server         │
  │  Targets:     │     │  (user-configured)   │
  │  - KaBum      │     │  - Price alerts      │
  │  - Shopee     │     │  - Failure warnings  │
  │  - Amazon BR  │     │  - Weekly summaries  │
  └──────────────┘     └──────────────────────┘
```

## Data Flow

1. **Add Product**: User submits URL → store auto-detected → product saved to SQLite
2. **Scrape Cycle** (every 6h):
   - APScheduler triggers `run_all_scrapes()`
   - For each active product, Playwright opens headless Chromium
   - Store-specific scraper extracts price using CSS selectors + regex fallback
   - Price recorded in `price_history` table
   - Alert thresholds evaluated → NTFY notification if triggered
   - On failure: failure count incremented → NTFY after 3 failures → auto-disable after 10
3. **Dashboard**: Reads from SQLite, renders charts via Chart.js
4. **Prune**: Old data (>365 days) deleted after each scrape cycle

## Database Schema

```sql
products (logical grouping — one per tracked item)
  id              INTEGER PRIMARY KEY
  name            TEXT NOT NULL
  alert_price_abs REAL          -- absolute price threshold
  alert_price_pct REAL          -- percentage drop threshold
  alert_below_mean INTEGER      -- boolean: alert when below mean
  active          INTEGER       -- boolean: tracking enabled
  created_at      TIMESTAMP

product_links (individual URLs per product)
  id              INTEGER PRIMARY KEY
  product_id      INTEGER → products.id
  url             TEXT NOT NULL UNIQUE
  store           TEXT CHECK(store IN ('kabum','shopee','amazon','aliexpress','terabyte','generic'))
  custom_selector TEXT          -- user-picked CSS selector (nullable)
  pre_actions     TEXT          -- JSON array of recorded pre-scrape actions (nullable)
  consecutive_failures INTEGER  -- failure counter per link
  created_at      TIMESTAMP

price_history
  id          INTEGER PRIMARY KEY
  link_id     INTEGER → product_links.id
  price       REAL              -- null on failure
  status      TEXT CHECK(status IN ('success','failed','blocked'))
  error_message TEXT
  scraped_at  TIMESTAMP
```

One product can have multiple links (e.g., same GPU on KaBum + Amazon + AliExpress).
Stats are computed across all links for a product.

## Scraper Strategy

- **Playwright Chromium** headless with stealth patches
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
5. User clicks on the price → system generates a CSS selector
6. Preview shows the extracted text for verification
7. User confirms → selector saved to `product_links.custom_selector`

**Scrape priority per link:**
1. Custom selector (if set) → tried first (with pre_actions replay)
2. Store-specific cascade → CSS → JSON-LD → meta → regex
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
├── main.py           # FastAPI app, lifespan, router registration
├── config.py         # Pydantic settings
├── database.py       # SQLite connection, schema, init
├── models.py         # Pydantic models
├── scheduler.py      # APScheduler setup, scrape orchestration
├── routers/
│   ├── dashboard.py  # Dashboard page
│   ├── products.py   # Product CRUD + detail
│   ├── alerts.py     # Alert history page
│   ├── settings.py   # NTFY, backup, restore
│   ├── api.py        # JSON endpoints for charts
│   └── picker.py     # Element picker API (load, confirm, clear)
├── scrapers/
│   ├── base.py       # BaseScraper (Playwright lifecycle, BRL parser, cascade, custom_selector)
│   ├── kabum.py      # KaBum scraper
│   ├── shopee.py     # Shopee scraper
│   ├── amazon.py     # Amazon Brazil scraper
│   ├── aliexpress.py # AliExpress scraper
│   ├── terabyte.py   # Terabyte scraper
│   ├── generic.py    # Generic scraper (any website, custom_selector → cascade)
│   └── registry.py   # Store detection + scraper factory + SSRF validation
├── services/
│   ├── price_service.py   # Stats, history, comparison
│   ├── alert_service.py   # Threshold evaluation, failure handling
│   ├── ntfy_service.py    # NTFY push notifications
│   └── backup_service.py  # Export, import, prune
├── templates/        # Jinja2 HTML templates
│   ├── base.html
│   ├── dashboard.html
│   ├── products.html
│   ├── product_detail.html
│   ├── alerts.html
│   ├── settings.html
│   ├── logs.html
│   └── picker.html   # Element picker UI (screenshot overlay)
└── static/
    └── js/charts.js  # Chart.js utilities
```
