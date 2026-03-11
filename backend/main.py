"""
Amazon Buybox Tracker - FastAPI Backend
Fetches buybox price and seller info for Amazon ASINs
"""

import time
import random
import os
import re
import io
import csv
import requests
import threading
import uuid
import httpx
from datetime import datetime
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from bs4 import BeautifulSoup
from loguru import logger
from database import init_db, get_db, save_asin, save_price_history, get_all_asins, get_price_history, delete_asin, TrackedASIN, PriceHistory, SessionLocal, engine
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
    logger.info(f"[job {job_id}] Starting bulk job with {len(asins)} ASINs")
    
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"

    results = []
    failed = []

    # Use a dedicated DB session for this thread
    db = SessionLocal()
    try:
        for i, asin in enumerate(asins):
            try:
                logger.info(f"[job {job_id}] Scraping ASIN {i+1}/{len(asins)}: {asin}")
                data = scrape_with_retry(asin, marketplace)
                save_asin(db, data)
                if data.get("status") == "success":
                    save_price_history(db, data)
                    results.append(data)
                    logger.info(f"[job {job_id}] ✅ {asin}: {data.get('buybox_seller', 'Unknown')}")
                else:
                    failed.append({"asin": asin, "error": data.get("error", "Unknown error")})
                    logger.warning(f"[job {job_id}] ❌ {asin}: {data.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"[job {job_id}] Error scraping {asin}: {e}")
                failed.append({"asin": asin, "error": str(e)})

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
        try:
            db.close()
        except Exception as e:
            logger.error(f"[job {job_id}] Error closing DB: {e}")

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
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
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


def get_offer_listing_data(asin: str, marketplace: str = "amazon.co.za") -> dict:
    """
    Scrape the 'All Buying Options' page when main page doesn't show seller.
    URL: https://www.amazon.co.za/gp/offer-listing/ASIN
    """
    url = f"https://www.{marketplace}/gp/offer-listing/{asin}"
    headers = random.choice(HEADERS_LIST)
    
    logger.info(f"Fetching offer-listing page for ASIN: {asin}")
    
    try:
        session = requests.Session()
        time.sleep(random.uniform(2.5, 4.5))  # Slightly longer delay for secondary page
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        
        if response.status_code != 200:
            logger.warning(f"Offer-listing page returned {response.status_code} for {asin}")
            return None
        
        soup = BeautifulSoup(response.content, "lxml")
        
        # Find the first offer (usually the buybox winner or lowest price)
        offer_divs = soup.find_all("div", {"class": "a-row a-spacing-mini olpOffer"})
        
        if not offer_divs:
            logger.warning(f"No offers found on offer-listing page for {asin}")
            return None
        
        # Get the first (best) offer
        first_offer = offer_divs[0]
        
        # Extract price
        price = None
        price_span = first_offer.find("span", {"class": "a-price"})
        if price_span:
            price_whole = price_span.find("span", {"class": "a-price-whole"})
            price_fraction = price_span.find("span", {"class": "a-price-fraction"})
            if price_whole:
                whole_text = price_whole.get_text(strip=True).replace(",", "").replace(" ", "").replace("R", "").strip()
                frac_text = price_fraction.get_text(strip=True).strip() if price_fraction else "00"
                try:
                    price = float(f"{whole_text}.{frac_text}")
                except Exception:
                    pass
        
        # If still no price, try offscreen price
        if not price:
            offscreen = first_offer.find("span", {"class": "a-offscreen"})
            if offscreen:
                price = parse_price(offscreen.get_text(strip=True))
        
        # Extract seller name - FIXED: More precise extraction
        seller = None
        
        # Method 1: Check for seller link/name in h3.olpSellerName
        seller_h3 = first_offer.find("h3", {"class": "a-spacing-none olpSellerName"})
        if seller_h3:
            # Look for link first
            seller_link = seller_h3.find("a")
            if seller_link:
                seller_text = seller_link.get_text(strip=True)
                seller = seller_text
            else:
                # If no link, check for span or direct text
                seller_span = seller_h3.find("span")
                if seller_span:
                    seller_text = seller_span.get_text(strip=True)
                    seller = seller_text
                else:
                    seller_text = seller_h3.get_text(strip=True)
                    if seller_text and seller_text != "Amazon.co.za":
                        seller = seller_text
        
        # Method 2: Look for merchant info in offer
        if not seller:
            merchant_link = first_offer.find("a", {"aria-label": lambda x: x and "seller" in x.lower()})
            if merchant_link:
                seller = merchant_link.get_text(strip=True)
        
        # Method 3: Check "Sold by" text patterns
        if not seller:
            offer_text = first_offer.get_text(" ", strip=True)
            # Only mark as Amazon if explicitly stated
            if re.search(r'sold by amazon\.co\.za|ships from and sold by amazon', offer_text, re.I):
                seller = "Amazon.co.za"
            else:
                # Try to extract seller from "Sold by X" pattern
                sold_by_match = re.search(r'Sold by\s+([^\.\n]{2,50}?)(?:\s|$)', offer_text)
                if sold_by_match:
                    seller = sold_by_match.group(1).strip()
        
        if price and seller:
            logger.success(f"✅ Found from offer-listing: Price={price}, Seller={seller}")
            return {"price": price, "seller": seller}
        
        return None
        
    except Exception as e:
        logger.error(f"Error scraping offer-listing for {asin}: {e}")
        return None


def get_amazon_buybox(asin: str, marketplace: str = "amazon.co.za") -> dict:
    """Scrape Amazon product page for buybox info."""

    url = f"https://www.{marketplace}/dp/{asin}"
    headers = random.choice(HEADERS_LIST)

    logger.info(f"Fetching buybox data for ASIN: {asin} from {url}")

    try:
        session = requests.Session()
        # Add a small delay to avoid rate limiting - increased for refresh stability
        time.sleep(random.uniform(2.5, 4.5))

        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
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

        # --- FALLBACK: If no seller/price found, try offer-listing page ---
        if not seller or not price:
            logger.info(f"Main page missing data for {asin}, trying offer-listing page...")
            offer_data = get_offer_listing_data(asin, marketplace)
            if offer_data:
                if not price and offer_data.get("price"):
                    price = offer_data["price"]
                    result["buybox_price"] = price
                    logger.info(f"✅ Got price from offer-listing: {price}")
                if not seller and offer_data.get("seller"):
                    seller = offer_data["seller"]
                    logger.info(f"✅ Got seller from offer-listing: {seller}")

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
        rating_text = rating_el.get("title", "").split(" ")[0] if rating_el else None
        # Convert rating to float, handle errors
        try:
            result["rating"] = float(rating_text) if rating_text else None
        except (ValueError, TypeError):
            result["rating"] = None

        reviews_el = soup.find("span", {"id": "acrCustomerReviewText"})
        if reviews_el:
            review_text = reviews_el.get_text(strip=True).split(" ")[0]
            # Clean review count: remove parentheses, commas, and convert to int
            review_text = review_text.replace("(", "").replace(")", "").replace(",", "").strip()
            try:
                result["review_count"] = int(review_text) if review_text.isdigit() else None
            except (ValueError, TypeError):
                result["review_count"] = None
        else:
            result["review_count"] = None

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
    import threading
    def _bg():
        try:
            init_db()
            _migrate_db()
            logger.info("Database initialized")
        except Exception as e:
            logger.error(f"DB init error: {e}")
    threading.Thread(target=_bg, daemon=True).start()
    if SCHEDULER_AVAILABLE:
        try:
            start_scheduler()
            logger.info("Scheduler started")
        except Exception as e:
            logger.error(f"Scheduler failed to start: {e}")


def _migrate_db():
    """Add new columns to existing tables without dropping data."""
    try:
        with engine.connect() as conn:
            # Check and add sku, my_price, my_stock columns
            for col, col_type in [("sku", "VARCHAR(255)"), ("my_price", "FLOAT"), ("my_stock", "INTEGER"), ("cost_price", "FLOAT"), ("cost_supplier", "VARCHAR(255)")]:
                try:
                    conn.execute(text(f"ALTER TABLE tracked_asins ADD COLUMN {col} {col_type}"))
                    conn.commit()
                    logger.info(f"✅ Migration: added column '{col}' to tracked_asins")
                except Exception:
                    pass  # Column already exists — safe to ignore
    except Exception as e:
        logger.warning(f"Migration skipped: {e}")

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
        "url": f"https://www.{a.marketplace}/dp/{a.asin}", "status": "success",
        # My seller data
        "sku": a.sku, "my_price": a.my_price, "my_stock": a.my_stock,
        # Cost data
        "cost_price": a.cost_price, "cost_supplier": a.cost_supplier,
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
    try:
        asin_pattern = re.compile(r'^[A-Z0-9]{10}$')
        asins = [a.strip().upper() for a in req.asins if a.strip()]
        asins = [a for a in asins if asin_pattern.match(a)]
        
        logger.info(f"Bulk start received {len(asins)} valid ASINs from {len(req.asins)} inputs")
        
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk start error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start bulk job: {str(e)}")


@app.get("/api/buybox/bulk-status/{job_id}")
def bulk_status(job_id: str):
    """Poll the status of a background bulk scrape job."""
    try:
        with _jobs_lock:
            job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk status error for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


# ===== CHROME EXTENSION API ENDPOINTS =====
@app.post("/api/extension/scrape")
def extension_scrape(data: dict):
    """
    Receive scraped data from Chrome extension and save to database.
    This bypasses all bot detection since data comes from real browser.
    Field names from extension: asin, title, seller, price, currency,
    rating, review_count, availability, image_url, marketplace,
    is_amazon, buybox_status, scraped_at
    """
    try:
        logger.info(f"📦 Received extension data: {data}")

        # Extract and validate ASIN
        asin = (data.get("asin") or "").strip().upper()
        if not asin or len(asin) != 10:
            raise HTTPException(status_code=400, detail=f"Invalid ASIN: '{asin}'")

        # Determine buybox status - extension sends buybox_status already
        # but also re-check against MY_SELLER_NAME for safety
        seller = data.get("seller") or "Unknown"
        ext_status = data.get("buybox_status", "unknown")
        is_amazon = bool(data.get("is_amazon", False)) or bool(re.search(r'\bamazon\b', seller, re.I))
        is_mine = MY_SELLER_NAME.lower() in seller.lower() if seller else False
        if is_mine:
            buybox_status = "winning"
        elif is_amazon:
            buybox_status = "amazon"
        elif ext_status and ext_status != "unknown":
            buybox_status = ext_status
        elif seller and seller != "Unknown":
            buybox_status = "losing"
        else:
            buybox_status = "unknown"

        # Normalise marketplace - strip www. prefix if present
        marketplace = (data.get("marketplace") or "amazon.co.za").replace("www.", "")

        # Map extension field names → database field names
        db_data = {
            "asin": asin,
            "title": data.get("title"),
            "image_url": data.get("image_url"),
            "marketplace": marketplace,
            "buybox_price": data.get("price"),
            "buybox_seller": seller,
            "buybox_status": buybox_status,
            "currency": data.get("currency", "ZAR"),
            "rating": data.get("rating"),
            "review_count": data.get("review_count"),
            "availability": data.get("availability", "Unknown"),
            "is_amazon_seller": is_amazon,
            "scraped_at": datetime.now(),
        }

        # Save to database
        db = SessionLocal()
        try:
            existing = db.query(TrackedASIN).filter(TrackedASIN.asin == asin).first()
            if existing:
                for key, value in db_data.items():
                    if key != "created_at" and hasattr(existing, key):
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
                logger.info(f"✅ Updated ASIN {asin} from extension — seller={seller}, status={buybox_status}")
            else:
                new_asin = TrackedASIN(**db_data)
                db.add(new_asin)
                logger.info(f"✅ Created new ASIN {asin} from extension — seller={seller}, status={buybox_status}")

            db.commit()

            # Save price history entry
            if db_data.get("buybox_price"):
                save_price_history(db, {
                    "asin": asin,
                    "marketplace": marketplace,
                    "buybox_price": db_data["buybox_price"],
                    "buybox_seller": seller,
                    "buybox_status": buybox_status,
                })

            return {
                "success": True,
                "message": f"ASIN {asin} saved successfully",
                "asin": asin,
                "buybox_status": buybox_status,
                "seller": seller,
                "source": "chrome_extension"
            }
        finally:
            db.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Extension scrape error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save extension data: {str(e)}")


# ============================================================================
# Import Job Store (in-memory, for progress tracking)
# ============================================================================

# import_job_id -> { status, total, done, updated, skipped, error, finished_at }
_import_jobs: Dict[str, dict] = {}
_import_jobs_lock = threading.Lock()

IMPORT_CHUNK_SIZE = 100  # commit every N rows to avoid long transactions


def _parse_import_rows(content: bytes, filename: str):
    """Parse CSV or Excel file bytes into a list of row dicts."""
    rows = []
    if filename.endswith(".csv"):
        text_content = content.decode("utf-8-sig", errors="replace")
        # Auto-detect delimiter (semicolon or comma)
        sample = text_content[:2048]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)
        rows = list(reader)
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        headers = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c).strip() if c else "" for c in row]
            else:
                rows.append(dict(zip(headers, [str(c).strip() if c is not None else "" for c in row])))
        wb.close()
    return rows


def _find_col(row, *names):
    """Flexible column name matching (case-insensitive, ignores spaces/underscores)."""
    normalised_names = [n.lower().replace(" ", "").replace("_", "") for n in names]
    for k in row:
        if k.lower().replace(" ", "").replace("_", "") in normalised_names:
            val = row[k]
            return val.strip() if val else None
    return None


def _run_import_job(job_id: str, content: bytes, filename: str):
    """Background thread: parse file and upsert into DB in chunks, updating progress."""
    logger.info(f"[import {job_id}] Starting import of {filename}")
    with _import_jobs_lock:
        _import_jobs[job_id]["status"] = "parsing"

    try:
        rows = _parse_import_rows(content, filename)
    except Exception as e:
        logger.error(f"[import {job_id}] Parse error: {e}")
        with _import_jobs_lock:
            _import_jobs[job_id]["status"] = "error"
            _import_jobs[job_id]["error"] = f"File parse error: {str(e)}"
            _import_jobs[job_id]["finished_at"] = datetime.now().isoformat()
        return

    total = len(rows)
    with _import_jobs_lock:
        _import_jobs[job_id]["status"] = "importing"
        _import_jobs[job_id]["total"] = total

    logger.info(f"[import {job_id}] Parsed {total} rows, importing in chunks of {IMPORT_CHUNK_SIZE}...")

    asin_re = re.compile(r'^[A-Z0-9]{10}$')
    updated_count = 0
    skipped_count = 0
    skipped_reasons = []

    db = SessionLocal()
    try:
        for chunk_start in range(0, total, IMPORT_CHUNK_SIZE):
            chunk = rows[chunk_start: chunk_start + IMPORT_CHUNK_SIZE]

            for row in chunk:
                asin = (_find_col(row, "ASIN", "asin") or "").upper().strip()
                if not asin or not asin_re.match(asin):
                    skipped_count += 1
                    if len(skipped_reasons) < 50:
                        skipped_reasons.append({"reason": "Invalid or missing ASIN"})
                    continue

                sku = _find_col(row, "SKU", "sku", "Seller SKU", "SellerSKU")
                my_price_raw = _find_col(row, "My Price", "MyPrice", "Price", "my_price", "YourPrice")
                stock_raw = _find_col(row, "Stock", "Qty", "Quantity", "stock", "StockLevel", "AvailableQty")

                my_price = None
                if my_price_raw:
                    try:
                        my_price = float(re.sub(r'[^\d.]', '', my_price_raw))
                    except Exception:
                        pass

                my_stock = None
                if stock_raw:
                    try:
                        my_stock = int(re.sub(r'[^\d]', '', stock_raw))
                    except Exception:
                        pass

                try:
                    existing = db.query(TrackedASIN).filter(TrackedASIN.asin == asin).first()
                    if existing:
                        if sku is not None:
                            existing.sku = sku
                        if my_price is not None:
                            existing.my_price = my_price
                        if my_stock is not None:
                            existing.my_stock = my_stock
                        existing.updated_at = datetime.utcnow()
                    else:
                        new_rec = TrackedASIN(
                            asin=asin, sku=sku, my_price=my_price, my_stock=my_stock,
                            marketplace="amazon.co.za", buybox_status="unknown",
                            title=f"Pending scrape... ({asin})", scraped_at=None,
                        )
                        db.add(new_rec)
                    updated_count += 1
                except Exception as e:
                    logger.warning(f"[import {job_id}] Row error for ASIN {asin}: {e}")
                    skipped_count += 1
                    if len(skipped_reasons) < 50:
                        skipped_reasons.append({"reason": f"DB error for {asin}: {str(e)}"})

            # Commit after each chunk
            try:
                db.commit()
            except Exception as e:
                logger.error(f"[import {job_id}] Commit error at chunk {chunk_start}: {e}")
                db.rollback()

            # Update progress
            done_so_far = min(chunk_start + IMPORT_CHUNK_SIZE, total)
            with _import_jobs_lock:
                _import_jobs[job_id]["done"] = done_so_far
                _import_jobs[job_id]["updated"] = updated_count
                _import_jobs[job_id]["skipped"] = skipped_count

            logger.info(f"[import {job_id}] Progress: {done_so_far}/{total} rows processed ({updated_count} imported, {skipped_count} skipped)")

    except Exception as e:
        logger.error(f"[import {job_id}] Unexpected error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        with _import_jobs_lock:
            _import_jobs[job_id]["status"] = "error"
            _import_jobs[job_id]["error"] = str(e)
            _import_jobs[job_id]["finished_at"] = datetime.now().isoformat()
        return
    finally:
        try:
            db.close()
        except Exception:
            pass

    with _import_jobs_lock:
        _import_jobs[job_id]["status"] = "done"
        _import_jobs[job_id]["done"] = total
        _import_jobs[job_id]["updated"] = updated_count
        _import_jobs[job_id]["skipped"] = skipped_count
        _import_jobs[job_id]["skipped_reasons"] = skipped_reasons
        _import_jobs[job_id]["finished_at"] = datetime.now().isoformat()

    logger.info(f"[import {job_id}] ✅ Finished: {updated_count} imported, {skipped_count} skipped")


@app.post("/api/import/excel")
async def import_excel(file: UploadFile = File(...)):
    """
    Start a background import job for ASIN/SKU/Price/Stock from Excel or CSV.
    Returns a job_id to poll /api/import/excel-status/{job_id} for progress.
    Handles up to 5000+ rows by processing in chunks of 100 with progress tracking.
    """
    try:
        filename = (file.filename or "").lower()
        if not (filename.endswith(".csv") or filename.endswith(".xlsx") or filename.endswith(".xls")):
            raise HTTPException(status_code=400, detail="Only .xlsx, .xls, or .csv files are supported")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="File is empty")

        # Check openpyxl available for Excel files
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            try:
                import openpyxl  # noqa
            except ImportError:
                raise HTTPException(status_code=500, detail="openpyxl not installed. Use CSV format instead.")

        job_id = str(uuid.uuid4())
        with _import_jobs_lock:
            _import_jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "filename": file.filename,
                "total": 0,
                "done": 0,
                "updated": 0,
                "skipped": 0,
                "skipped_reasons": [],
                "error": None,
                "started_at": datetime.now().isoformat(),
                "finished_at": None,
            }

        t = threading.Thread(target=_run_import_job, args=(job_id, content, filename), daemon=True)
        t.start()

        logger.info(f"Started import job {job_id} for file '{file.filename}'")
        return {"job_id": job_id, "status": "queued", "filename": file.filename}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Excel import start error: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed to start: {str(e)}")


@app.get("/api/import/excel-status/{job_id}")
def import_excel_status(job_id: str):
    """Poll the progress of a background import job."""
    with _import_jobs_lock:
        job = _import_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@app.get("/api/extension/config")
def extension_config():
    """Return configuration for Chrome extension."""
    return {
        "seller_name": MY_SELLER_NAME,
        "marketplace": "amazon.co.za",
        "version": "1.0.0"
    }


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

GSHEET_ID = "1ISaEOPBElufeYh6eq6APtlFjeMvrKqlAwEd3F4K6rBw"

# All supplier tabs: gid, supplier name, SKU column index, Cost Price column index
# Column index is 0-based. -1 means skip this tab (no cost column).
GSHEET_TABS = [
    {"gid": "683374593",  "supplier": "Pinnacle",        "sku_col": 0, "cost_col": 4},
    {"gid": "1303527933", "supplier": "Tarsus",           "sku_col": 0, "cost_col": 5},
    {"gid": "1631360215", "supplier": "Rectron",          "sku_col": 0, "cost_col": 5},
    {"gid": "1663080928", "supplier": "Axiz",             "sku_col": 0, "cost_col": 4},
    {"gid": "1947555616", "supplier": "SMD",              "sku_col": 0, "cost_col": 4},
    {"gid": "606695391",  "supplier": "Mustek",           "sku_col": 0, "cost_col": 5},
    {"gid": "420604899",  "supplier": "Esquire Products", "sku_col": 0, "cost_col": 6},
    {"gid": "2088256006", "supplier": "Kolok",            "sku_col": 0, "cost_col": 3},
    {"gid": "1013794846", "supplier": "Cost Data",        "sku_col": 0, "cost_col": 1},
    {"gid": "854400299",  "supplier": "DCC",              "sku_col": 0, "cost_col": 4},
    {"gid": "214462025",  "supplier": "VAST-Maynards",    "sku_col": 0, "cost_col": 3},
]


def _parse_cost(raw: str) -> float | None:
    """Strip R prefix, spaces and commas then parse as float."""
    cleaned = raw.replace("R", "").replace(",", "").replace("\xa0", "").strip()
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


@app.get("/api/costs/sync-gsheet")
async def sync_costs_from_gsheet(db: Session = Depends(get_db)):
    """Fetch cost prices from ALL supplier tabs in the Google Sheet and update matched products by SKU.
    Each tab is fetched individually. The FIRST match (lowest cost supplier priority order) wins,
    unless a later tab has a lower cost — in that case both are recorded via cost_supplier field.
    """
    # Build master lookup: sku_lower -> {cost_price, supplier}
    sheet_lookup: dict = {}

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for tab in GSHEET_TABS:
            url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={tab['gid']}"
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"GSheet tab {tab['supplier']} (gid={tab['gid']}) fetch failed: {e}")
                continue

            reader = csv.reader(io.StringIO(resp.text))
            for i, row in enumerate(reader):
                if i == 0:
                    continue  # skip header row
                if len(row) <= max(tab["sku_col"], tab["cost_col"]):
                    continue
                sku_raw = row[tab["sku_col"]].strip()
                if not sku_raw:
                    continue
                cost_val = _parse_cost(row[tab["cost_col"]])
                if cost_val is None or cost_val <= 0:
                    continue
                sku_key = sku_raw.lower()
                # Keep the entry with the LOWEST cost (best buy price) across all suppliers
                existing = sheet_lookup.get(sku_key)
                if existing is None or cost_val < existing["cost_price"]:
                    sheet_lookup[sku_key] = {
                        "cost_price": cost_val,
                        "supplier": tab["supplier"],
                        "sku_original": sku_raw,
                    }

    logger.info(f"GSheet sync: built lookup with {len(sheet_lookup)} unique SKUs across {len(GSHEET_TABS)} tabs")

    # Match tracked products by SKU and update cost_price + cost_supplier
    all_products = get_all_asins(db)
    matched = 0
    updated = 0
    not_found = []

    for product in all_products:
        sku = (product.sku or "").strip()
        if not sku:
            continue
        entry = sheet_lookup.get(sku.lower())
        if entry:
            matched += 1
            product.cost_price = entry["cost_price"]
            product.cost_supplier = entry["supplier"]
            product.updated_at = datetime.utcnow()
            updated += 1
        else:
            not_found.append(sku)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB commit failed: {str(e)}")

    logger.info(f"GSheet cost sync: {matched} matched, {updated} updated, {len(not_found)} not found")
    return {
        "matched": matched,
        "updated": updated,
        "not_found": not_found,
        "sheet_skus_loaded": len(sheet_lookup),
        "tabs_fetched": len(GSHEET_TABS),
    }


# ── My Price sync from Google Sheet ──────────────────────────────────────────
# Tab name: "My Prices"  |  Columns: SKU (col 0), My Price (col 1)
# Create a tab in your sheet with header row:  SKU | My Price
# Then paste your SKUs + selling prices there. This endpoint reads it and
# updates my_price in the DB for every matched SKU.

GSHEET_MYPRICES_GID = os.getenv("GSHEET_MYPRICES_GID", "")  # set via Render env var

@app.get("/api/costs/sync-myprices-gsheet")
async def sync_myprices_from_gsheet(db: Session = Depends(get_db)):
    """Read My Price column from the 'My Prices' Google Sheet tab and update matched SKUs."""
    gid = GSHEET_MYPRICES_GID
    if not gid:
        raise HTTPException(status_code=400, detail="GSHEET_MYPRICES_GID env var not set. Add the tab gid to Render.")

    url = f"https://docs.google.com/spreadsheets/d/{GSHEET_ID}/export?format=csv&gid={gid}"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch Google Sheet: {e}")

    # Parse CSV — skip header row, expect: SKU | My Price
    price_lookup: dict = {}
    reader = csv.reader(io.StringIO(resp.text))
    for i, row in enumerate(reader):
        if i == 0:
            continue  # skip header
        if len(row) < 2:
            continue
        sku_raw = row[0].strip()
        price_raw = row[1].strip()
        if not sku_raw or not price_raw:
            continue
        try:
            price_val = float(re.sub(r'[^\d.]', '', price_raw))
        except Exception:
            continue
        if price_val > 0:
            price_lookup[sku_raw.lower()] = {"my_price": price_val, "sku_original": sku_raw}

    logger.info(f"My Prices GSheet: loaded {len(price_lookup)} SKU prices")

    all_products = get_all_asins(db)
    matched = updated = 0
    not_found = []

    for product in all_products:
        sku = (product.sku or "").strip()
        if not sku:
            continue
        entry = price_lookup.get(sku.lower())
        if entry:
            matched += 1
            product.my_price = entry["my_price"]
            product.updated_at = datetime.utcnow()
            updated += 1
        else:
            not_found.append(sku)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB commit failed: {str(e)}")

    logger.info(f"My Prices sync: {updated} updated, {len(not_found)} not matched")
    return {
        "updated": updated,
        "matched": matched,
        "not_found_count": len(not_found),
        "sheet_skus_loaded": len(price_lookup),
    }


class CostUpdateRequest(BaseModel):
    asin: str
    cost_price: float


@app.post("/api/costs/update")
def update_cost_price(req: CostUpdateRequest, db: Session = Depends(get_db)):
    """Update the cost_price for a single ASIN."""
    asin = req.asin.strip().upper()
    product = db.query(TrackedASIN).filter(TrackedASIN.asin == asin).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"ASIN {asin} not found")
    product.cost_price = req.cost_price
    product.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(product)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB commit failed: {str(e)}")
    logger.info(f"Updated cost_price for {asin}: {req.cost_price}")
    return asin_to_dict(product)


class SkuUpdateRequest(BaseModel):
    asin: str
    sku: str

@app.post("/api/costs/update-sku")
def update_sku(req: SkuUpdateRequest, db: Session = Depends(get_db)):
    """Update the SKU for a single ASIN so Google Sheet cost sync can match it."""
    asin = req.asin.strip().upper()
    product = db.query(TrackedASIN).filter(TrackedASIN.asin == asin).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"ASIN {asin} not found")
    product.sku = req.sku.strip()
    product.updated_at = datetime.utcnow()
    try:
        db.commit()
        db.refresh(product)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB commit failed: {str(e)}")
    logger.info(f"Updated SKU for {asin}: {req.sku}")
    return {"ok": True, "asin": asin, "sku": product.sku}


# ============================================================================
# SP-API Endpoints — Price Push, Credential Check, Listings Sync
# ============================================================================

try:
    from sp_api_client import push_price, fetch_my_listings, check_credentials, get_competitive_pricing
    SP_API_AVAILABLE = True
    logger.info("sp_api_client loaded successfully")
except Exception as e:
    SP_API_AVAILABLE = False
    logger.warning(f"sp_api_client not available: {e}")


class PushPriceRequest(BaseModel):
    sku: str
    price: float
    asin: str = ""  # for logging/response only


@app.post("/api/amazon/push-price")
def api_push_price(req: PushPriceRequest, db: Session = Depends(get_db)):
    """Push a new price to Amazon for a given SKU via SP-API."""
    if not SP_API_AVAILABLE:
        raise HTTPException(status_code=503, detail="SP-API client not available")
    if not req.sku:
        raise HTTPException(status_code=400, detail="SKU is required")
    if not req.price or req.price <= 0:
        raise HTTPException(status_code=400, detail="Price must be greater than 0")

    result = push_price(sku=req.sku, new_price=req.price)

    # Log the push attempt in DB as a price_history note
    if result.get("ok") and req.asin:
        try:
            save_price_history(db, {
                "asin": req.asin.strip().upper(),
                "marketplace": "amazon.co.za",
                "buybox_price": req.price,
                "buybox_seller": "Bonolo Online (pushed)",
                "buybox_status": "pushed",
            })
        except Exception:
            pass

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "Push failed"))

    return result


@app.get("/api/amazon/check-credentials")
def api_check_credentials():
    """Verify SP-API credentials are working."""
    if not SP_API_AVAILABLE:
        return {"ok": False, "message": "SP-API client module not loaded"}
    return check_credentials()


@app.get("/api/amazon/my-listings")
def api_my_listings():
    """Fetch all active listings from Amazon Seller Central."""
    if not SP_API_AVAILABLE:
        raise HTTPException(status_code=503, detail="SP-API client not available")
    result = fetch_my_listings(limit=100)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("message", "Fetch failed"))
    return result


@app.post("/api/amazon/sync-listings")
def api_sync_listings(db: Session = Depends(get_db)):
    """
    Fetch listings from Amazon and sync prices/quantities into our DB.
    Matches on SKU → updates my_price and my_stock for matched products.
    """
    if not SP_API_AVAILABLE:
        raise HTTPException(status_code=503, detail="SP-API client not available")

    result = fetch_my_listings(limit=200)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("message", "Fetch failed"))

    listings = result.get("listings", [])
    updated = 0
    not_found = []

    for listing in listings:
        sku = listing.get("sku", "")
        amazon_price = listing.get("price")
        amazon_qty = listing.get("quantity")

        if not sku:
            continue

        product = db.query(TrackedASIN).filter(TrackedASIN.sku == sku).first()
        if product:
            if amazon_price is not None:
                product.my_price = float(amazon_price)
            if amazon_qty is not None:
                product.my_stock = int(amazon_qty)
            product.updated_at = datetime.utcnow()
            updated += 1
        else:
            not_found.append(sku)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"DB commit failed: {str(e)}")

    logger.info(f"Listings sync: {updated} updated, {len(not_found)} SKUs not in DB")
    return {
        "ok": True,
        "updated": updated,
        "total_from_amazon": len(listings),
        "skus_not_in_db": not_found,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
