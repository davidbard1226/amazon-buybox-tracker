"""
Amazon Buybox Tracker - FastAPI Backend
Fetches buybox price and seller info for Amazon ASINs
"""

import time
import random
import os
import re
import requests
import threading
import uuid
from datetime import datetime
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from bs4 import BeautifulSoup
from loguru import logger
from database import init_db, get_db, save_asin, save_price_history, get_all_asins, get_price_history, delete_asin, TrackedASIN, PriceHistory, SessionLocal
try:
    from alerts import send_whatsapp_alert, send_telegram_alert, load_alert_settings, save_alert_settings
    from scheduler import start_scheduler, stop_scheduler, get_scheduler_status, update_scheduler_interval, refresh_all_asins
    SCHEDULER_AVAILABLE = True
    logger.info("Scheduler and alerts modules loaded successfully")
except Exception as e:
    SCHEDULER_AVAILABLE = False
    logger.warning(f"Scheduler/alerts not available: {e}")

# ============================================================================
# FastAPI App Setup
# ============================================================================

app = FastAPI(
    title="Amazon Buybox Tracker API",
    description="Track Amazon buybox prices and sellers by ASIN",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Your seller name
MY_SELLER_NAME = os.getenv("MY_SELLER_NAME", "Bonolo Online")

# ============================================================================
# Models
# ============================================================================

class ASINRequest(BaseModel):
    asin: str
    marketplace: str = "amazon.co.za"

class BulkASINRequest(BaseModel):
    asins: List[str]
    marketplace: str = "amazon.co.za"

class BulkURLRequest(BaseModel):
    urls: List[str]
    marketplace: str = "amazon.co.za"

# ============================================================================
# Background Job Store (in-memory, survives for the lifetime of the process)
# ============================================================================

# job_id -> { status, total, done, results, failed, started_at, finished_at }
_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_bulk_job(job_id: str, asins: List[str], marketplace: str):
    """Scrape ASINs in a background thread, updating job status as we go."""
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    results = []
    failed = []

    # Use a dedicated DB session for this thread
    db = SessionLocal()
    try:
        for i, asin in enumerate(asins):
            data = scrape_with_retry(asin, marketplace)
            save_asin(db, data)
            if data.get("status") == "success":
                save_price_history(db, data)
                results.append(data)
            else:
                failed.append({"asin": asin, "error": data.get("error", "Unknown error")})

            with _jobs_lock:
                _jobs[job_id]["done"] = i + 1
                _jobs[job_id]["results"] = results[:]
                _jobs[job_id]["failed"] = failed[:]

            # Progressive delay: longer cooldown every 10 products
            if (i + 1) % 10 == 0 and (i + 1) < len(asins):
                wait = random.uniform(10, 20)
                logger.info(f"[job {job_id}] Processed {i+1}/{len(asins)}, cooling down {wait:.1f}s...")
                time.sleep(wait)
            elif (i + 1) < len(asins):
                time.sleep(random.uniform(2, 4))
    except Exception as e:
        logger.error(f"[job {job_id}] Unexpected error: {e}")
        with _jobs_lock:
            _jobs[job_id]["error"] = str(e)
    finally:
        db.close()

    with _jobs_lock:
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["finished_at"] = datetime.now().isoformat()

    logger.info(f"[job {job_id}] Finished: {len(results)} ok, {len(failed)} failed")

# ============================================================================
# Amazon Scraper
# ============================================================================

HEADERS_LIST = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    }
]


def parse_price(raw: str) -> float:
    """Parse price string handling multiple formats including SA (R1 660,00), UK (£53.48), US ($12.99)."""
    if not raw:
        return None
    # Remove currency symbols and non-breaking spaces
    cleaned = raw.replace("\xa0", "").replace("\u202f", "")
    cleaned = cleaned.replace("R", "").replace("£", "").replace("$", "").replace("€", "").replace("A$", "").replace("C$", "").strip()
    # SA format: 1 660,00 (space thousands, comma decimal)
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(" ", "").replace(",", ".")
    # US/UK format: 1,660.00 (comma thousands, dot decimal)
    elif "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    # No separator issues
    else:
        cleaned = cleaned.replace(" ", "").replace(",", "")
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except Exception:
        return None


def get_amazon_buybox(asin: str, marketplace: str = "amazon.co.za") -> dict:
    """Scrape Amazon product page for buybox info."""

    url = f"https://www.{marketplace}/dp/{asin}"
    headers = random.choice(HEADERS_LIST)

    logger.info(f"Fetching buybox data for ASIN: {asin} from {url}")

    try:
        session = requests.Session()
        # Add a small delay to avoid rate limiting
        time.sleep(random.uniform(1.5, 3.0))

        response = session.get(url, headers=headers, timeout=15)
        logger.info(f"Response status: {response.status_code}")

        if response.status_code == 503:
            return {
                "asin": asin,
                "status": "blocked",
                "error": "Amazon blocked the request (503). Try again shortly.",
                "url": url,
                "scraped_at": datetime.now().isoformat()
            }

        if response.status_code != 200:
            return {
                "asin": asin,
                "status": "error",
                "error": f"HTTP {response.status_code}",
                "url": url,
                "scraped_at": datetime.now().isoformat()
            }

        soup = BeautifulSoup(response.content, "lxml")

        result = {
            "asin": asin,
            "url": url,
            "marketplace": marketplace,
            "scraped_at": datetime.now().isoformat(),
            "status": "success",
        }

        # --- Product Title ---
        title_el = (
            soup.find("span", {"id": "productTitle"}) or
            soup.find("h1", {"id": "title"})
        )
        result["title"] = title_el.get_text(strip=True) if title_el else "Unknown"

        # --- Buybox Price ---
        price = None
        price_selectors = [
            {"id": "priceblock_ourprice"},
            {"id": "priceblock_dealprice"},
            {"class": "a-price-whole"},
            {"id": "price_inside_buybox"},
            {"class": "priceToPay"},
        ]

        def extract_price_from_block(block):
            """Extract price from any soup block, handles whole+fraction or combined spans."""
            if not block:
                return None
            # Try whole + fraction pattern
            price_el = block.find("span", {"class": "a-price-whole"})
            frac_el = block.find("span", {"class": "a-price-fraction"})
            if price_el:
                whole = price_el.get_text(strip=True).replace(",", "").replace(".", "").replace("R", "").strip()
                frac = frac_el.get_text(strip=True).strip() if frac_el else "00"
                frac = frac.replace(",", "").replace(".", "").strip()
                if whole.isdigit():
                    try:
                        return float(f"{whole}.{frac if frac.isdigit() else '00'}")
                    except Exception:
                        pass
            # Try a-offscreen (hidden full price text)
            offscreen = block.find("span", {"class": "a-offscreen"})
            if offscreen:
                raw = offscreen.get_text(strip=True)
                price = parse_price(raw)
                if price:
                    return price
            return None

        # Try all known price container IDs
        price_container_ids = [
            "corePriceDisplay_desktop_feature_div",
            "apex_desktop",
            "buybox",
            "buyNewSection",
            "price",
            "tmmSwatches",
        ]
        for container_id in price_container_ids:
            block = soup.find(attrs={"id": container_id})
            price = extract_price_from_block(block)
            if price:
                break

        # Fallback: search whole page for a-offscreen price spans
        if not price:
            for span in soup.find_all("span", {"class": "a-offscreen"}):
                raw = span.get_text(strip=True)
                val = parse_price(raw)
                if val and val > 0:
                    price = val
                    break

        # Final fallback: old-style price IDs
        if not price:
            for sel in price_selectors:
                el = soup.find("span", sel)
                if el:
                    raw = el.get_text(strip=True).replace(",", "").replace("£", "").replace("$", "").replace("R", "").strip()
                    try:
                        price = float(raw)
                        break
                    except Exception:
                        continue

        result["buybox_price"] = price
        if "amazon.co.za" in marketplace:
            result["currency"] = "ZAR"
        elif "amazon.co.uk" in marketplace:
            result["currency"] = "GBP"
        elif "amazon.de" in marketplace or "amazon.fr" in marketplace:
            result["currency"] = "EUR"
        elif "amazon.ca" in marketplace:
            result["currency"] = "CAD"
        elif "amazon.com.au" in marketplace:
            result["currency"] = "AUD"
        else:
            result["currency"] = "USD"

        # --- Buybox Seller ---
        seller = None
        page_text = soup.get_text(" ", strip=True)

        # 1. Try sellerProfileTriggerId - most reliable for 3rd party sellers
        seller_link = soup.find("a", {"id": "sellerProfileTriggerId"})
        if seller_link:
            seller = seller_link.get_text(strip=True)

        # 2. Check offer-display-feature-text-message spans (shows seller name inline)
        if not seller:
            for span in soup.find_all("span", {"class": "offer-display-feature-text-message"}):
                text = span.get_text(strip=True)
                if text:
                    if re.search(r'amazon', text, re.I):
                        seller = "Amazon.co.za"
                    else:
                        seller = text
                    break

        # 3. Check merchant-info div
        if not seller:
            merchant = soup.find("div", {"id": "merchant-info"})
            if merchant:
                a_tag = merchant.find("a")
                if a_tag:
                    seller = a_tag.get_text(strip=True)
                else:
                    txt = merchant.get_text(strip=True)
                    if re.search(r'amazon', txt, re.I):
                        seller = "Amazon.co.za"

        # 4. Check tabular-buybox "Sold by" row
        if not seller:
            tabular = soup.find("div", {"id": "tabular-buybox"})
            if tabular:
                for row in tabular.find_all("div", {"class": "tabular-buybox-text"}):
                    label = row.find("span", {"class": "a-color-secondary"})
                    val = row.find("span", {"class": "a-color-base"})
                    if label and val and "Sold by" in label.get_text():
                        seller = val.get_text(strip=True)
                        break

        # 5. KEY FIX: "Sent from and sold by Amazon.co.za" pattern in a-color-secondary spans
        if not seller:
            for span in soup.find_all("span", {"class": lambda c: c and "a-color-secondary" in c}):
                txt = span.get_text(strip=True)
                if re.search(r'sold by amazon', txt, re.I):
                    seller = "Amazon.co.za"
                    break

        # 6. Search full page text for "Sold by X" or "sold and fulfilled by X"
        if not seller:
            # "Sold by SomeSeller" pattern
            match = re.search(r'Sold by\s+([^\.\n\|]{2,60}?)(?:\s*\.|$|\s*Fulfilled|\s*Ships)', page_text)
            if match:
                name = match.group(1).strip()
                if re.search(r'amazon', name, re.I):
                    seller = "Amazon.co.za"
                else:
                    seller = name

        # 7. Final check: "Sent from and sold by Amazon" anywhere in page
        if not seller:
            if re.search(r'(sent from and sold by|sold and fulfilled by|ships from and sold by)\s*amazon', page_text, re.I):
                seller = "Amazon.co.za"

        # --- Determine buybox status ---
        seller_lower = (seller or "").lower().strip()
        is_amazon = bool(re.search(r'\bamazon\b', seller_lower))
        is_mine = MY_SELLER_NAME.lower() in seller_lower

        result["buybox_seller"] = seller if seller else "Unknown"
        result["is_amazon_seller"] = is_amazon
        result["is_my_buybox"] = is_mine
        result["buybox_status"] = (
            "winning" if is_mine
            else "amazon" if is_amazon
            else "losing" if seller
            else "unknown"
        )

        # --- Rating & Reviews ---
        rating_el = soup.find("span", {"id": "acrPopover"})
        result["rating"] = rating_el.get("title", "").split(" ")[0] if rating_el else None

        reviews_el = soup.find("span", {"id": "acrCustomerReviewText"})
        result["review_count"] = reviews_el.get_text(strip=True).split(" ")[0].replace(",", "") if reviews_el else None

        # --- Availability ---
        avail_el = soup.find("div", {"id": "availability"})
        result["availability"] = avail_el.get_text(strip=True) if avail_el else "Unknown"

        # --- Product Image ---
        img_el = soup.find("img", {"id": "landingImage"}) or soup.find("img", {"id": "imgBlkFront"})
        result["image_url"] = img_el.get("src") or img_el.get("data-a-dynamic-image", "").split('"')[1] if img_el else None

        logger.success(f"✅ ASIN {asin}: Price={price}, Seller={seller}")
        return result

    except requests.exceptions.Timeout:
        logger.error(f"Timeout for ASIN {asin}")
        return {"asin": asin, "status": "error", "error": "Request timed out", "url": url, "scraped_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"Error scraping ASIN {asin}: {e}")
        return {"asin": asin, "status": "error", "error": str(e), "url": url, "scraped_at": datetime.now().isoformat()}


# ============================================================================
# API Endpoints
# ============================================================================

@app.on_event("startup")
def startup_event():
    try:
        init_db()
        logger.info("Database initialized on startup")
    except Exception as e:
        logger.error(f"Startup DB init error (app will still start): {e}")
    if SCHEDULER_AVAILABLE:
        try:
            start_scheduler()
            logger.info("Scheduler started")
        except Exception as e:
            logger.error(f"Scheduler failed to start: {e}")

@app.on_event("shutdown")
def shutdown_event():
    if SCHEDULER_AVAILABLE:
        stop_scheduler()
        logger.info("Scheduler stopped")

# Serve static files (dashboard)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_dashboard():
    index = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    return FileResponse(index)

@app.get("/api/health")
def health():
    db_status = "unknown"
    count = 0
    db_error = None
    try:
        db = next(get_db())
        count = db.query(TrackedASIN).count()
        db_status = "connected"
        db.close()
    except Exception as e:
        db_status = "error"
        db_error = str(e)
        logger.error(f"Health check DB error: {e}")
    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "timestamp": datetime.now().isoformat(),
        "tracked_asins": count,
        "scheduler_available": SCHEDULER_AVAILABLE,
        "database": db_status,
        "database_error": db_error,
        "version": "2.0.0"
    }


def asin_to_dict(a: TrackedASIN) -> dict:
    return {
        "asin": a.asin, "title": a.title, "image_url": a.image_url,
        "marketplace": a.marketplace, "buybox_price": a.buybox_price,
        "buybox_seller": a.buybox_seller, "buybox_status": a.buybox_status,
        "currency": a.currency, "rating": a.rating, "review_count": a.review_count,
        "availability": a.availability, "is_amazon_seller": a.is_amazon_seller,
        "scraped_at": a.scraped_at.isoformat() if a.scraped_at else None,
        "url": f"https://www.{a.marketplace}/dp/{a.asin}", "status": "success"
    }


@app.post("/api/buybox/lookup")
def lookup_buybox(req: ASINRequest, db: Session = Depends(get_db)):
    asin = req.asin.strip().upper()
    if not asin:
        raise HTTPException(status_code=400, detail="ASIN is required")
    data = get_amazon_buybox(asin, req.marketplace)
    save_asin(db, data)
    save_price_history(db, data)
    return data


def scrape_with_retry(asin: str, marketplace: str, max_retries: int = 3) -> dict:
    """Scrape an ASIN with retry logic on blocks/errors."""
    for attempt in range(1, max_retries + 1):
        data = get_amazon_buybox(asin, marketplace)
        if data.get("status") == "success":
            return data
        if data.get("status") == "blocked":
            wait = random.uniform(8, 15) * attempt
            logger.warning(f"ASIN {asin} blocked (attempt {attempt}/{max_retries}), waiting {wait:.1f}s...")
            time.sleep(wait)
        elif data.get("status") == "error":
            wait = random.uniform(3, 6)
            logger.warning(f"ASIN {asin} error (attempt {attempt}/{max_retries}): {data.get('error')}, waiting {wait:.1f}s...")
            time.sleep(wait)
        else:
            break
    return data  # return last result even if failed


@app.post("/api/buybox/bulk")
def bulk_lookup(req: BulkASINRequest, db: Session = Depends(get_db)):
    results = []
    failed = []
    asins = [a.strip().upper() for a in req.asins if a.strip()]
    logger.info(f"Bulk scrape started for {len(asins)} ASINs")
    for i, asin in enumerate(asins):
        data = scrape_with_retry(asin, req.marketplace)
        save_asin(db, data)
        if data.get("status") == "success":
            save_price_history(db, data)
            results.append(data)
        else:
            failed.append({"asin": asin, "error": data.get("error", "Unknown error")})
        # Progressive delay: longer every 10 products to avoid rate limiting
        if (i + 1) % 10 == 0:
            wait = random.uniform(10, 20)
            logger.info(f"Processed {i+1}/{len(asins)}, cooling down {wait:.1f}s...")
            time.sleep(wait)
        else:
            time.sleep(random.uniform(3, 6))
    logger.info(f"Bulk scrape done: {len(results)} success, {len(failed)} failed")
    return {"results": results, "count": len(results), "failed": failed, "failed_count": len(failed)}


@app.post("/api/buybox/bulk-start")
def bulk_start(req: BulkASINRequest):
    """Start a background bulk scrape job. Returns a job_id to poll for progress."""
    asin_pattern = re.compile(r'^[A-Z0-9]{10}$')
    asins = [a.strip().upper() for a in req.asins if a.strip()]
    asins = [a for a in asins if asin_pattern.match(a)]
    if not asins:
        raise HTTPException(status_code=400, detail="No valid ASINs provided")

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "total": len(asins),
            "done": 0,
            "results": [],
            "failed": [],
            "marketplace": req.marketplace,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "error": None,
        }

    t = threading.Thread(target=_run_bulk_job, args=(job_id, asins, req.marketplace), daemon=True)
    t.start()
    logger.info(f"Started bulk job {job_id} for {len(asins)} ASINs")
    return {"job_id": job_id, "total": len(asins), "status": "queued"}


@app.get("/api/buybox/bulk-status/{job_id}")
def bulk_status(job_id: str):
    """Poll the status of a background bulk scrape job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/buybox/bulk-add")
def bulk_add_asins(req: BulkASINRequest, db: Session = Depends(get_db)):
    """Instantly save ASINs to the database without scraping.
    They will be scraped in the background by the scheduler."""
    asin_pattern = re.compile(r'^[A-Z0-9]{10}$')
    added = []
    skipped = []
    for asin in req.asins:
        asin = asin.strip().upper()
        if not asin or not asin_pattern.match(asin):
            skipped.append(asin)
            continue
        # Save a placeholder record so it appears in dashboard immediately
        save_asin(db, {
            "asin": asin,
            "marketplace": req.marketplace,
            "status": "pending",
            "title": f"Pending scrape... ({asin})",
            "buybox_status": "unknown",
        })
        added.append(asin)
    logger.info(f"Bulk-add: {len(added)} ASINs saved, {len(skipped)} skipped")
    return {"added": added, "added_count": len(added), "skipped": skipped,
            "message": f"{len(added)} ASINs added. They will be scraped on the next scheduler run."}


@app.post("/api/buybox/bulk-urls")
def bulk_url_lookup(req: BulkURLRequest, db: Session = Depends(get_db)):
    asin_pattern = re.compile(r"/dp/([A-Z0-9]{10})", re.I)
    asins = []
    for url in req.urls:
        url = url.strip()
        if not url:
            continue
        if re.match(r'^[A-Z0-9]{10}$', url, re.I):
            asins.append(url.upper())
            continue
        match = asin_pattern.search(url)
        if match:
            asins.append(match.group(1).upper())
        else:
            logger.warning(f"Could not extract ASIN from: {url}")
    results = []
    failed = []
    logger.info(f"Bulk URL scrape started for {len(asins)} ASINs")
    for i, asin in enumerate(asins):
        data = scrape_with_retry(asin, req.marketplace)
        save_asin(db, data)
        if data.get("status") == "success":
            save_price_history(db, data)
            results.append(data)
        else:
            failed.append({"asin": asin, "error": data.get("error", "Unknown error")})
        if (i + 1) % 10 == 0:
            wait = random.uniform(10, 20)
            logger.info(f"Processed {i+1}/{len(asins)}, cooling down {wait:.1f}s...")
            time.sleep(wait)
        else:
            time.sleep(random.uniform(3, 6))
    return {"results": results, "count": len(results), "failed": failed, "failed_count": len(failed), "asins_found": asins}


@app.get("/api/buybox/tracked")
def get_tracked(db: Session = Depends(get_db)):
    asins = get_all_asins(db)
    return {"asins": [asin_to_dict(a) for a in asins], "count": len(asins)}


@app.get("/api/buybox/history/{asin}")
def get_history(asin: str, db: Session = Depends(get_db)):
    asin = asin.upper()
    history = get_price_history(db, asin)
    return {
        "asin": asin,
        "history": [{"timestamp": h.timestamp.isoformat(), "price": h.price, "seller": h.seller, "status": h.status} for h in history],
        "count": len(history)
    }


@app.delete("/api/buybox/tracked/{asin}")
def remove_asin(asin: str, db: Session = Depends(get_db)):
    asin = asin.upper()
    delete_asin(db, asin)
    return {"message": f"ASIN {asin} removed from tracking"}


@app.get("/api/buybox/stats")
def get_stats(db: Session = Depends(get_db)):
    asins = get_all_asins(db)
    total = len(asins)
    winning = len([a for a in asins if a.buybox_status == "winning"])
    losing = len([a for a in asins if a.buybox_status == "losing"])
    amazon_wins = len([a for a in asins if a.buybox_status == "amazon"])
    prices = [a.buybox_price for a in asins if a.buybox_price]
    avg_price = round(sum(prices) / len(prices), 2) if prices else 0
    return {
        "total_tracked": total,
        "winning": winning,
        "losing": losing,
        "amazon_wins": amazon_wins,
        "avg_buybox_price": avg_price,
        "last_updated": datetime.now().isoformat()
    }


@app.get("/api/alerts/settings")
def get_alert_settings():
    if not SCHEDULER_AVAILABLE:
        return {"whatsapp_phone": "", "callmebot_apikey": "", "alert_losing": True, "alert_winning": True, "alert_amazon": True}
    return load_alert_settings()

@app.post("/api/alerts/settings")
def update_alert_settings(settings: dict):
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Alerts module not available")
    save_alert_settings(settings)
    return {"message": "Settings saved", "settings": settings}

@app.post("/api/alerts/test")
def test_whatsapp():
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Alerts module not available")
    settings = load_alert_settings()
    phone = settings.get("whatsapp_phone")
    apikey = settings.get("callmebot_apikey")
    if not phone or not apikey:
        raise HTTPException(status_code=400, detail="WhatsApp phone and CallMeBot API key required")
    success = send_whatsapp_alert(
        phone=phone, apikey=apikey,
        message="Test alert from your Amazon Buybox Tracker! Alerts are working correctly."
    )
    return {"success": success, "message": "Test alert sent!" if success else "Failed to send alert"}

@app.post("/api/alerts/test-telegram")
def test_telegram():
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Alerts module not available")
    settings = load_alert_settings()
    bot_token = settings.get("telegram_bot_token")
    chat_id = settings.get("telegram_chat_id")
    if not bot_token or not chat_id:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    success = send_telegram_alert(
        bot_token=bot_token,
        chat_id=chat_id,
        message="🤖 <b>Test alert</b> from your Amazon Buybox Tracker!\n\nTelegram alerts are working correctly ✅"
    )
    return {"success": success, "message": "Telegram test sent!" if success else "Failed to send Telegram alert"}

@app.get("/api/scheduler/status")
def scheduler_status():
    if not SCHEDULER_AVAILABLE:
        return {"enabled": False, "interval_hours": 6.0, "running": False, "last_run": None, "next_run": None, "total_asins": 0, "error": "Scheduler module not loaded"}
    return get_scheduler_status()

class SchedulerSettings(BaseModel):
    interval_hours: float = 6.0
    enabled: bool = True

@app.post("/api/scheduler/settings")
def update_scheduler(settings: SchedulerSettings, db: Session = Depends(get_db)):
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Scheduler module not available")
    update_scheduler_interval(settings.interval_hours, settings.enabled, db)
    return {"message": f"Scheduler updated - runs every {settings.interval_hours} hours", "enabled": settings.enabled}

@app.post("/api/scheduler/run-now")
def run_now(db: Session = Depends(get_db)):
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="Scheduler module not available")
    refresh_all_asins(db)
    return {"message": "Manual refresh triggered for all tracked ASINs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
