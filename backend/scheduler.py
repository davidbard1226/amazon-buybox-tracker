"""
Auto-refresh scheduler using Python built-in threading - no extra dependencies

NOTE on Render.com: scheduler_settings.json won't persist across restarts.
Set SCHEDULER_INTERVAL_HOURS and SCHEDULER_ENABLED as Render env vars instead.
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
    """Load scheduler settings: env vars first, then file override."""
    try:
        default_interval = float(os.getenv("SCHEDULER_INTERVAL_HOURS", "6.0"))
    except ValueError:
        default_interval = 6.0
    enabled_env = os.getenv("SCHEDULER_ENABLED", "true").lower()
    default_enabled = enabled_env not in ("false", "0", "no")

    defaults = {"interval_hours": default_interval, "enabled": default_enabled}

    if os.path.exists(SCHEDULER_FILE):
        try:
            with open(SCHEDULER_FILE, "r") as f:
                defaults.update(json.load(f))
        except Exception:
            pass
    return defaults

def save_scheduler_settings(settings: dict):
    """Save to file (runtime cache only - resets on Render restart)."""
    try:
        with open(SCHEDULER_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        logger.error(f"Could not save scheduler settings: {e}")

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
                    # Enrich with DB fields so alert messages have SKU, my_price, title
                    enriched = dict(new_data)
                    enriched.setdefault("sku", a.sku)
                    enriched.setdefault("my_price", a.my_price)
                    enriched.setdefault("title", a.title or new_data.get("title"))
                    enriched.setdefault("cost_price", getattr(a, "cost_price", None))
                    check_and_alert(old_status, enriched)
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
    _enabled = settings.get("enabled", False)
    if _enabled:
        _schedule_next()
        logger.info(f"Scheduler started - runs every {_interval_hours} hours")
    else:
        logger.info("Scheduler disabled by default - using Chrome Extension for scraping")
    # Start daily summary if DAILY_SUMMARY_TIME env var is set (e.g. "08:00")
    _schedule_daily_summary()

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


# ============================================================================
# Daily Summary Scheduler
# ============================================================================

_daily_timer = None
_daily_last_sent = None


def _schedule_daily_summary():
    """Schedule the daily Telegram summary at the time set in DAILY_SUMMARY_TIME env var."""
    global _daily_timer
    summary_time = os.getenv("DAILY_SUMMARY_TIME", "").strip()
    if not summary_time:
        return
    try:
        h, m = map(int, summary_time.split(":"))
    except Exception:
        logger.error(f"Invalid DAILY_SUMMARY_TIME: {summary_time!r} — expected HH:MM")
        return

    now    = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    delay  = (target - now).total_seconds()
    _daily_timer = threading.Timer(delay, _fire_daily_summary)
    _daily_timer.daemon = True
    _daily_timer.start()
    logger.info(f"Daily summary scheduled for {target.strftime('%Y-%m-%d %H:%M')}")


def _fire_daily_summary():
    """Execute the daily summary and reschedule for tomorrow."""
    global _daily_last_sent
    logger.info("Firing daily intelligence summary")
    ok = trigger_daily_summary_now()
    if ok:
        _daily_last_sent = datetime.now().isoformat()
    _schedule_daily_summary()


def trigger_daily_summary_now() -> bool:
    """Manually fire the daily summary — called from API or schedule."""
    try:
        from database import SessionLocal, get_all_asins
        from sqlalchemy import text as sql_text
        from alerts import send_daily_summary

        db = SessionLocal()
        try:
            asins = get_all_asins(db)
            products = [
                {
                    "asin": a.asin, "sku": a.sku, "title": a.title,
                    "buybox_status": a.buybox_status, "buybox_price": a.buybox_price,
                    "buybox_seller": a.buybox_seller, "my_price": a.my_price,
                    "min_price": getattr(a, "min_price", None),
                    "currency": a.currency or "R",
                }
                for a in asins
            ]
            rows = db.execute(
                sql_text("SELECT asin, seller, price, status, timestamp FROM price_history ORDER BY timestamp DESC LIMIT 2000")
            ).fetchall()
            history = [
                {"asin": r[0], "seller": r[1], "price": r[2], "status": r[3], "timestamp": r[4]}
                for r in rows
            ]
        finally:
            db.close()

        return send_daily_summary(products, history)
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        return False
