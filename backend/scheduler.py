"""
Auto-refresh scheduler using Python built-in threading - no extra dependencies
"""
import os
import json
import threading
from datetime import datetime, timedelta
from loguru import logger

SCHEDULER_FILE = "scheduler_settings.json"

_timer = None
_last_run = None
_interval_hours = 6.0
_enabled = True
_next_run = None

def load_scheduler_settings() -> dict:
    if os.path.exists(SCHEDULER_FILE):
        try:
            with open(SCHEDULER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"interval_hours": 6.0, "enabled": True}

def save_scheduler_settings(settings: dict):
    with open(SCHEDULER_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def refresh_all_asins(db=None):
    global _last_run, _next_run, _interval_hours, _enabled, _timer
    logger.info("Scheduler: Starting auto-refresh of all tracked ASINs")
    _last_run = datetime.now().isoformat()
    try:
        from database import get_all_asins, save_asin, save_price_history, SessionLocal
        from main import get_amazon_buybox
        from alerts import check_and_alert
        import time, random
        db_session = SessionLocal()
        try:
            asins = get_all_asins(db_session)
            logger.info(f"Scheduler: Refreshing {len(asins)} ASINs")
            for a in asins:
                try:
                    old_status = a.buybox_status
                    new_data = get_amazon_buybox(a.asin, a.marketplace)
                    save_asin(db_session, new_data)
                    save_price_history(db_session, new_data)
                    check_and_alert(old_status, new_data)
                    time.sleep(random.uniform(3, 6))
                except Exception as e:
                    logger.error(f"Scheduler error for {a.asin}: {e}")
        finally:
            db_session.close()
        logger.success(f"Scheduler: Refresh complete for {len(asins)} ASINs")
    except Exception as e:
        logger.error(f"Scheduler refresh failed: {e}")
    # Schedule next run
    if _enabled:
        _schedule_next()

def _schedule_next():
    global _timer, _next_run, _interval_hours
    _next_run = (datetime.now() + timedelta(hours=_interval_hours)).isoformat()
    _timer = threading.Timer(_interval_hours * 3600, refresh_all_asins)
    _timer.daemon = True
    _timer.start()
    logger.info(f"Next refresh scheduled for: {_next_run}")

def start_scheduler():
    global _interval_hours, _enabled
    settings = load_scheduler_settings()
    _interval_hours = settings.get("interval_hours", 6.0)
    _enabled = settings.get("enabled", True)
    if _enabled:
        _schedule_next()
        logger.info(f"Scheduler started - runs every {_interval_hours} hours")
    else:
        logger.info("Scheduler disabled")

def stop_scheduler():
    global _timer
    if _timer:
        _timer.cancel()
        logger.info("Scheduler stopped")

def update_scheduler_interval(interval_hours: float, enabled: bool, db=None):
    global _interval_hours, _enabled, _timer
    _interval_hours = interval_hours
    _enabled = enabled
    save_scheduler_settings({"interval_hours": interval_hours, "enabled": enabled})
    if _timer:
        _timer.cancel()
    if enabled:
        _schedule_next()
        logger.info(f"Scheduler updated - every {interval_hours} hours")

def get_scheduler_status() -> dict:
    global _last_run, _next_run, _interval_hours, _enabled
    settings = load_scheduler_settings()
    from database import SessionLocal, TrackedASIN
    try:
        db = SessionLocal()
        total = db.query(TrackedASIN).count()
        db.close()
    except Exception:
        total = 0
    return {
        "enabled": settings.get("enabled", True),
        "interval_hours": settings.get("interval_hours", 6.0),
        "running": _timer is not None and _timer.is_alive(),
        "last_run": _last_run,
        "next_run": _next_run,
        "total_asins": total,
    }
