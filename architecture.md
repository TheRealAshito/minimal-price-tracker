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
products
  id              INTEGER PRIMARY KEY
  name            TEXT NOT NULL
  url             TEXT NOT NULL UNIQUE
  store           TEXT CHECK(store IN ('kabum','shopee','amazon'))
  alert_price_abs REAL          -- absolute price threshold
  alert_price_pct REAL          -- percentage drop threshold
  alert_below_mean INTEGER      -- boolean: alert when below mean
  consecutive_failures INTEGER  -- failure counter
  active          INTEGER       -- boolean: tracking enabled
  created_at      TIMESTAMP

price_history
  id          INTEGER PRIMARY KEY
  product_id  INTEGER → products.id
  price       REAL              -- null on failure
  status      TEXT CHECK(status IN ('success','failed','blocked'))
  error_message TEXT
  scraped_at  TIMESTAMP

settings
  key   TEXT PRIMARY KEY
  value TEXT
```

## Scraper Strategy

- **Playwright Chromium** headless with stealth patches
- **Rotating user-agents** from a pool of 5
- **Random delays** (2-8s) between requests
- **Multi-selector fallback**: tries CSS selectors, then regex on page source
- **JSON-LD extraction**: looks for structured data as last resort
- Per-store modules: fixing one store doesn't affect others

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
│   └── api.py        # JSON endpoints for charts
├── scrapers/
│   ├── base.py       # BaseScraper (Playwright lifecycle, BRL parser)
│   ├── kabum.py      # KaBum scraper
│   ├── shopee.py     # Shopee scraper
│   ├── amazon.py     # Amazon Brazil scraper
│   └── registry.py   # Store detection + scraper factory
├── services/
│   ├── price_service.py   # Stats, history, comparison
│   ├── alert_service.py   # Threshold evaluation, failure handling
│   ├── ntfy_service.py    # NTFY push notifications
│   └── backup_service.py  # Export, import, prune
├── templates/        # Jinja2 HTML templates
└── static/
    └── js/charts.js  # Chart.js utilities
```
