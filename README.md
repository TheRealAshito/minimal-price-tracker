# Minimal Price Tracker

A self-hosted, privacy-first price tracker for Brazilian e-commerce stores. Track prices on KaBum, Shopee, and Amazon Brazil with automatic scraping, alerts, and historical analysis.

## Features

- **Multi-store support**: KaBum, Shopee, Amazon Brazil
- **Automatic scraping**: Every 6 hours (configurable) via Playwright
- **Price analytics**: Min, max, mean, median, standard deviation
- **Smart alerts**: Absolute price, percentage drop, below historical average
- **NTFY integration**: Push notifications for price drops and failures
- **Historical charts**: Visual price tracking over time
- **Backup/restore**: Export/import your data anytime
- **Dark theme**: Easy on the eyes dashboard

## Quick Start

```bash
# Clone and run
git clone https://github.com/TheRealAshito/minimal-price-tracker.git
cd minimal-price-tracker
docker compose up -d --build
```

Open http://localhost:8035 in your browser.

## Adding Products

1. Go to **Products** → **Add Product**
2. Paste the product URL from KaBum, Shopee, or Amazon Brazil
3. The store is auto-detected from the URL
4. Configure alerts on the product detail page

## NTFY Setup

1. Go to **Settings**
2. Enter your NTFY server URL, port, and topic
3. Alerts will be pushed when prices drop or scrapes fail

## Tech Stack

- **Backend**: FastAPI + Python 3.12
- **Frontend**: Jinja2 + Tailwind CSS + Chart.js
- **Scraping**: Playwright (Chromium, headless)
- **Database**: SQLite
- **Deployment**: Docker Compose

## Security

- Bound to `127.0.0.1` only — no external network exposure
- No authentication needed (single-user, localhost only)
- No external API calls except NTFY (user-configured)
- SQLite data stays in your local `./data` volume

## License

MIT
