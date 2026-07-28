"""
In-memory log buffer for scraper activity.
Stores the last N log entries for viewing in the web UI.
"""
import logging
from collections import deque
from datetime import datetime
from typing import Optional

# Circular buffer — keeps last 500 entries
_log_buffer: deque[dict] = deque(maxlen=500)


class BufferHandler(logging.Handler):
    """Logging handler that stores records in the in-memory buffer."""

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            _log_buffer.append(entry)
        except Exception:
            pass


def setup_log_buffer():
    """Attach the buffer handler to the root logger."""
    handler = BufferHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    # Also ensure the price_tracker loggers are at DEBUG level
    logging.getLogger("price_tracker").setLevel(logging.DEBUG)
    logging.getLogger("price_tracker.scraper").setLevel(logging.DEBUG)
    logging.getLogger("price_tracker.scheduler").setLevel(logging.DEBUG)


def get_logs(level: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Get recent log entries, optionally filtered by level."""
    entries = list(_log_buffer)
    if level:
        entries = [e for e in entries if e["level"] == level.upper()]
    return entries[-limit:]


def get_log_stats() -> dict:
    """Get summary stats about the log buffer."""
    entries = list(_log_buffer)
    counts = {}
    for e in entries:
        counts[e["level"]] = counts.get(e["level"], 0) + 1
    return {
        "total": len(entries),
        "debug": counts.get("DEBUG", 0),
        "info": counts.get("INFO", 0),
        "warning": counts.get("WARNING", 0),
        "error": counts.get("ERROR", 0),
    }
