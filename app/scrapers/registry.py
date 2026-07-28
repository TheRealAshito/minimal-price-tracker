import ipaddress
from urllib.parse import urlparse
from app.scrapers.base import BaseScraper
from app.scrapers.kabum import KabumScraper
from app.scrapers.shopee import ShopeeScraper
from app.scrapers.amazon import AmazonScraper
from app.scrapers.aliexpress import AliExpressScraper
from app.scrapers.terabyte import TerabyteScraper

SCRAPERS = {
    "kabum": KabumScraper,
    "shopee": ShopeeScraper,
    "amazon": AmazonScraper,
    "aliexpress": AliExpressScraper,
    "terabyte": TerabyteScraper,
}

ALLOWED_STORE_DOMAINS = {
    "kabum": ["kabum.com.br"],
    "shopee": ["shopee.com.br", "shopee.sg", "shopee.cn"],
    "amazon": ["amazon.com.br", "amazon.com"],
    "aliexpress": ["aliexpress.com", "aliexpress.us", "aliexpress.ru"],
    "terabyte": ["terabyteshop.com.br"],
}


def get_scraper(store: str) -> BaseScraper:
    scraper_class = SCRAPERS.get(store)
    if not scraper_class:
        raise ValueError(f"Unknown store: {store}")
    return scraper_class()


def detect_store(url: str) -> str:
    """Auto-detect store from URL."""
    url_lower = url.lower()
    if "kabum.com.br" in url_lower:
        return "kabum"
    elif "shopee.com.br" in url_lower or "shopee." in url_lower:
        return "shopee"
    elif "amazon.com.br" in url_lower or "amazon." in url_lower:
        return "amazon"
    elif "aliexpress.com" in url_lower or "aliexpress." in url_lower:
        return "aliexpress"
    elif "terabyteshop.com.br" in url_lower or "terabyte.com.br" in url_lower:
        return "terabyte"
    raise ValueError(f"Could not detect store from URL: {url}")


def validate_url(url: str, store: str) -> str:
    """Validate URL is safe to scrape. Returns cleaned URL or raises ValueError."""
    parsed = urlparse(url)

    # Only allow http/https
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme '{parsed.scheme}' not allowed. Use http or https.")

    if not parsed.hostname:
        raise ValueError("URL has no hostname.")

    hostname = parsed.hostname.lower()

    # Block obvious internal hostnames
    if hostname in ("localhost", "0.0.0.0", "metadata.google.internal",
                     "169.254.169.254", "[::1]"):
        raise ValueError(f"Internal hostname not allowed: {hostname}")

    # Block private/internal/link-local IPs
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None  # Not an IP — hostname is a domain name, which is fine

    if ip is not None:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"Private/internal IP address not allowed: {hostname}")

    # Verify domain matches the detected store
    if store in ALLOWED_STORE_DOMAINS:
        allowed = ALLOWED_STORE_DOMAINS[store]
        if not any(hostname == d or hostname.endswith("." + d) for d in allowed):
            raise ValueError(
                f"URL domain '{hostname}' doesn't match store '{store}'. "
                f"Expected: {', '.join(allowed)}"
            )

    return url
