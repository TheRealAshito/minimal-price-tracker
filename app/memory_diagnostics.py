"""
Memory diagnostic utilities.
Reads from /proc/self/status (Linux) — no external dependencies needed.
"""
import os
import sys
import logging
from typing import Optional

logger = logging.getLogger("price_tracker.memory")


def _read_proc_status() -> dict:
    """Read memory info from /proc/self/status (Linux only)."""
    info = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    info["rss_kb"] = int(line.split()[1])
                elif line.startswith("VmSize:"):
                    info["vms_kb"] = int(line.split()[1])
                elif line.startswith("VmPeak:"):
                    info["vms_peak_kb"] = int(line.split()[1])
                elif line.startswith("VmHWM:"):
                    info["rss_peak_kb"] = int(line.split()[1])
                elif line.startswith("Threads:"):
                    info["threads"] = int(line.split()[1])
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return info


def _get_python_memory() -> dict:
    """Get Python-level memory stats."""
    stats = {}
    try:
        import gc
        stats["gc_objects"] = len(gc.get_objects())
        stats["gc_garbage"] = len(gc.garbage)
    except Exception:
        pass

    # Count loaded modules
    stats["loaded_modules"] = len(sys.modules)

    return stats


def get_memory_report() -> dict:
    """Full memory diagnostic report."""
    proc = _read_proc_status()
    python = _get_python_memory()

    rss_mb = proc.get("rss_kb", 0) / 1024
    vms_mb = proc.get("vms_kb", 0) / 1024
    rss_peak_mb = proc.get("rss_peak_kb", 0) / 1024
    vms_peak_mb = proc.get("vms_peak_kb", 0) / 1024

    # Check if browser is running
    browser_running = False
    browser_contexts = 0
    try:
        from app.browser_manager import browser_manager
        browser_running = browser_manager.is_running
    except Exception:
        pass

    # Check picker sessions
    picker_sessions = 0
    try:
        from app.routers.picker import _sessions
        picker_sessions = len(_sessions)
    except Exception:
        pass

    # Check scheduler state
    scheduler_jobs = 0
    try:
        from app.scheduler import scheduler
        scheduler_jobs = len(scheduler.get_jobs())
    except Exception:
        pass

    return {
        "process": {
            "rss_mb": round(rss_mb, 1),
            "vms_mb": round(vms_mb, 1),
            "rss_peak_mb": round(rss_peak_mb, 1),
            "vms_peak_mb": round(vms_peak_mb, 1),
            "threads": proc.get("threads", 0),
        },
        "python": {
            "gc_objects": python.get("gc_objects", 0),
            "gc_garbage": python.get("gc_garbage", 0),
            "loaded_modules": python.get("loaded_modules", 0),
        },
        "app": {
            "browser_running": browser_running,
            "picker_sessions": picker_sessions,
            "scheduler_jobs": scheduler_jobs,
        },
    }


def log_memory(label: str = ""):
    """Log current memory usage at a lifecycle point."""
    proc = _read_proc_status()
    rss_mb = proc.get("rss_kb", 0) / 1024
    prefix = f"[{label}] " if label else ""
    logger.info(f"{prefix}Memory: RSS={rss_mb:.1f}MB, threads={proc.get('threads', '?')}")
