"""
APScheduler - Auto-refresh all tracked ASINs on a schedule
"""
import os
import json
from datetime import datetime
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

SCHEDULER_FILE = "scheduler_settings.json"
scheduler = BackgroundScheduler()
_db_factory = None
_last_run = None
_interval_hours = 6.0
_enabled = True

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
    global _last_run, _db_factory
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

def start_scheduler():
    global _interval_hours, _enabled
    settings = load_scheduler_settings()
    _interval_hours = settings.get("interval_hours", 6.0)
    _enabled = settings.get("enabled", True)
    if _enabled:
        scheduler.add_job(
            refresh_all_asins,
            trigger=IntervalTrigger(hours=_interval_hours),
            id="refresh_all",
            replace_existing=True,
            name="Auto-refresh all ASINs"
        )
        scheduler.start()
        logger.info(f"Scheduler started - runs every {_interval_hours} hours")
    else:
        logger.info("Scheduler disabled - not starting")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

def update_scheduler_interval(interval_hours: float, enabled: bool, db=None):
    global _interval_hours, _enabled
    _interval_hours = interval_hours
    _enabled = enabled
    save_scheduler_settings({"interval_hours": interval_hours, "enabled": enabled})
    if scheduler.running:
        scheduler.remove_all_jobs()
        if enabled:
            scheduler.add_job(
                refresh_all_asins,
                trigger=IntervalTrigger(hours=interval_hours),
                id="refresh_all",
                replace_existing=True,
                name="Auto-refresh all ASINs"
            )
            logger.info(f"Scheduler updated - every {interval_hours} hours")
    elif enabled:
        start_scheduler()

def get_scheduler_status() -> dict:
    global _last_run, _interval_hours, _enabled
    settings = load_scheduler_settings()
    next_run = None
    try:
        job = scheduler.get_job("refresh_all")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    except Exception:
        pass
    from database import SessionLocal
    try:
        db = SessionLocal()
        from database import TrackedASIN
        total = db.query(TrackedASIN).count()
        db.close()
    except Exception:
        total = 0
    return {
        "enabled": settings.get("enabled", True),
        "interval_hours": settings.get("interval_hours", 6.0),
        "running": scheduler.running,
        "last_run": _last_run,
        "next_run": next_run,
        "total_asins": total,
    }
