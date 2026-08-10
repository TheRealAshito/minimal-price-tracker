"""
Date formatting utilities.
Shared across all routers via Jinja2 globals.
"""
from datetime import datetime

# Portuguese day/month names
_PT_DAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
_PT_MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
_EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _parse_dt(value: str) -> datetime | None:
    """Parse a datetime string in common formats."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:19], fmt)
        except (ValueError, IndexError):
            continue
    return None


def format_date(value: str, fmt: str = "DD/MM/YYYY") -> str:
    """Format a datetime string according to the user's preferred format."""
    dt = _parse_dt(value)
    if not dt:
        return value or ""
    d, m, y = dt.day, dt.month, dt.year
    try:
        if fmt == "DD/MM/YYYY":
            return f"{d:02d}/{m:02d}/{y}"
        elif fmt == "MM/DD/YYYY":
            return f"{m:02d}/{d:02d}/{y}"
        elif fmt == "YYYY-MM-DD":
            return f"{y}-{m:02d}-{d:02d}"
        elif fmt == "DD-MM-YYYY":
            return f"{d:02d}-{m:02d}-{y}"
        elif fmt == "DD Mon YYYY":
            return f"{d:02d} {_EN_MONTHS[m-1]} {y}"
        elif fmt == "Mon DD, YYYY":
            return f"{_EN_MONTHS[m-1]} {d:02d}, {y}"
        elif fmt == "DD/Mon/AAAA (PT)":
            return f"{d:02d}/{_PT_MONTHS[m-1]}/{y}"
        elif fmt == "Seg, 31 Ago 2026 (PT)":
            weekday = _PT_DAYS[dt.weekday()]
            return f"{weekday}, {d:02d} {_PT_MONTHS[m-1]} {y}"
        elif fmt == "DD/MM HH:MM":
            return f"{d:02d}/{m:02d} {dt.hour:02d}:{dt.minute:02d}"
        else:
            return f"{d:02d}/{m:02d}/{y}"
    except (IndexError, ValueError):
        return value or ""


def format_datetime(value: str, fmt: str = "DD/MM/YYYY") -> str:
    """Format a datetime string with time appended."""
    dt = _parse_dt(value)
    if not dt:
        return value or ""
    date_part = format_date(value, fmt)
    if fmt in ("Seg, 31 Ago 2026 (PT)", "DD/MM HH:MM"):
        return date_part
    return f"{date_part} {dt.hour:02d}:{dt.minute:02d}"
