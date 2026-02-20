"""
Amazon Buybox Tracker - FastAPI Backend
Fetches buybox price and seller info for Amazon ASINs
"""

import time
import random
import json
import os
import re
import requests
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pydantic import BaseModel
from bs4 import BeautifulSoup
from loguru import logger

# ============================================================================
# Persistence Setup
# ============================================================================

DATA_FILE = os.path.join(os.path.dirname(__file__), "tracker_data.json")

def load_data():
    """Load persisted data from disk."""
    global tracked_asins, price_history
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                tracked_asins.update(data.get("tracked_asins", {}))
                price_history.update(data.get("price_history", {}))
            logger.info(f"Loaded {len(tracked_asins)} ASINs from disk")
        except Exception as e:
            logger.error(f"Failed to load data: {e}")

def save_data():
    """Save current data to disk."""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"tracked_asins": tracked_asins, "price_history": price_history}, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save data: {e}")

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

# ============================================================================
# In-Memory Store
# ============================================================================

tracked_asins: Dict[str, dict] = {}
price_history: Dict[str, List[dict]] = {}

# Your seller name - change this if needed
MY_SELLER_NAME = "Bonolo Online"

# Amazon seller name variants
AMAZON_SELLER_NAMES = ["amazon", "amazon.co.za", "amazon.com", "fulfilled by amazon", "sold by amazon"]

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
    load_data()
    logger.info("Data loaded from disk on startup")

# Serve static files (dashboard)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_dashboard():
    """Serve the dashboard HTML."""
    index = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
    return FileResponse(index)

@app.get("/api/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat(), "tracked_asins": len(tracked_asins)}


@app.post("/api/buybox/lookup")
def lookup_buybox(req: ASINRequest):
    """Fetch live buybox data for a single ASIN."""
    asin = req.asin.strip().upper()
    if not asin:
        raise HTTPException(status_code=400, detail="ASIN is required")

    data = get_amazon_buybox(asin, req.marketplace)

    # Store in memory
    tracked_asins[asin] = data

    # Record price history
    if asin not in price_history:
        price_history[asin] = []

    if data.get("buybox_price"):
        price_history[asin].append({
            "timestamp": data["scraped_at"],
            "price": data["buybox_price"],
            "seller": data.get("buybox_seller"),
            "status": data.get("buybox_status"),
        })
        # Keep last 100 records
        price_history[asin] = price_history[asin][-100:]

    # Persist to disk
    save_data()

    return data


@app.post("/api/buybox/bulk")
def bulk_lookup(req: BulkASINRequest):
    """Fetch buybox data for multiple ASINs."""
    results = []
    for asin in req.asins:
        asin = asin.strip().upper()
        if asin:
            data = get_amazon_buybox(asin, req.marketplace)
            tracked_asins[asin] = data
            if asin not in price_history:
                price_history[asin] = []
            if data.get("buybox_price"):
                price_history[asin].append({
                    "timestamp": data["scraped_at"],
                    "price": data["buybox_price"],
                    "seller": data.get("buybox_seller"),
                    "status": data.get("buybox_status"),
                })
                price_history[asin] = price_history[asin][-100:]
            results.append(data)
            time.sleep(random.uniform(2, 4))  # Be polite between requests
    save_data()
    return {"results": results, "count": len(results)}


@app.post("/api/buybox/bulk-urls")
def bulk_url_lookup(req: BulkURLRequest):
    """Extract ASINs from Amazon URLs and fetch buybox data."""
    asin_pattern = re.compile(r"/dp/([A-Z0-9]{10})", re.I)
    asins = []
    for url in req.urls:
        url = url.strip()
        if not url:
            continue
        # If it's already an ASIN (10 chars alphanumeric)
        if re.match(r'^[A-Z0-9]{10}$', url, re.I):
            asins.append(url.upper())
            continue
        # Extract from URL
        match = asin_pattern.search(url)
        if match:
            asins.append(match.group(1).upper())
        else:
            logger.warning(f"Could not extract ASIN from: {url}")

    results = []
    for asin in asins:
        data = get_amazon_buybox(asin, req.marketplace)
        tracked_asins[asin] = data
        if asin not in price_history:
            price_history[asin] = []
        if data.get("buybox_price"):
            price_history[asin].append({
                "timestamp": data["scraped_at"],
                "price": data["buybox_price"],
                "seller": data.get("buybox_seller"),
                "status": data.get("buybox_status"),
            })
            price_history[asin] = price_history[asin][-100:]
        results.append(data)
        time.sleep(random.uniform(2, 4))
    save_data()
    return {"results": results, "count": len(results), "asins_found": asins}


@app.get("/api/buybox/tracked")
def get_tracked():
    """Get all tracked ASINs with their latest data."""
    return {"asins": list(tracked_asins.values()), "count": len(tracked_asins)}


@app.get("/api/buybox/history/{asin}")
def get_history(asin: str):
    """Get price history for a specific ASIN."""
    asin = asin.upper()
    history = price_history.get(asin, [])
    return {
        "asin": asin,
        "history": history,
        "count": len(history)
    }


@app.delete("/api/buybox/tracked/{asin}")
def remove_asin(asin: str):
    """Remove an ASIN from tracking."""
    asin = asin.upper()
    if asin in tracked_asins:
        del tracked_asins[asin]
    if asin in price_history:
        del price_history[asin]
    return {"message": f"ASIN {asin} removed from tracking"}


@app.get("/api/buybox/stats")
def get_stats():
    """Get summary stats for tracked ASINs."""
    asins = list(tracked_asins.values())
    total = len(asins)
    amazon_wins = len([a for a in asins if a.get("is_amazon_seller")])
    third_party_wins = total - amazon_wins

    prices = [a["buybox_price"] for a in asins if a.get("buybox_price")]
    avg_price = round(sum(prices) / len(prices), 2) if prices else 0

    return {
        "total_tracked": total,
        "amazon_wins": amazon_wins,
        "third_party_wins": third_party_wins,
        "avg_buybox_price": avg_price,
        "last_updated": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
