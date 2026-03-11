"""
Amazon SP-API Client — Price Push & Listings Sync
Uses python-amazon-sp-api library.
Credentials are loaded from environment variables set on Render.
"""

import os
import time
from loguru import logger
from datetime import datetime

# ── Credentials from environment ─────────────────────────────────
LWA_CLIENT_ID     = os.getenv("LWA_CLIENT_ID", "")
LWA_CLIENT_SECRET = os.getenv("LWA_CLIENT_SECRET", "")
AWS_ACCESS_KEY    = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY    = os.getenv("AWS_SECRET_ACCESS_KEY", "")
SELLER_ID         = os.getenv("SP_API_SELLER_ID", "")
MARKETPLACE_ID    = os.getenv("SP_API_MARKETPLACE_ID", "A1E5JOF6FQYU90")  # ZA default

CREDENTIALS = {
    "lwa_app_id":     LWA_CLIENT_ID,
    "lwa_client_secret": LWA_CLIENT_SECRET,
    "aws_secret_key": AWS_SECRET_KEY,
    "aws_access_key": AWS_ACCESS_KEY,
    "role_arn":       None,  # Not using IAM role, using direct IAM user
}

def _creds_ok() -> bool:
    """Check all required credentials are present."""
    missing = [k for k, v in {
        "LWA_CLIENT_ID": LWA_CLIENT_ID,
        "LWA_CLIENT_SECRET": LWA_CLIENT_SECRET,
        "AWS_ACCESS_KEY_ID": AWS_ACCESS_KEY,
        "AWS_SECRET_ACCESS_KEY": AWS_SECRET_KEY,
        "SP_API_SELLER_ID": SELLER_ID,
    }.items() if not v]
    if missing:
        logger.error(f"SP-API: Missing credentials: {missing}")
        return False
    return True

def push_price(sku: str, new_price: float, currency: str = "ZAR") -> dict:
    """
    Push a new price to Amazon for a given SKU using SP-API Listings API.
    Returns: { ok: bool, message: str, sku: str, price: float }
    """
    if not _creds_ok():
        return {"ok": False, "message": "SP-API credentials not configured", "sku": sku, "price": new_price}
    if not sku:
        return {"ok": False, "message": "SKU is required to push a price", "sku": sku, "price": new_price}
    if not new_price or new_price <= 0:
        return {"ok": False, "message": "Invalid price — must be greater than 0", "sku": sku, "price": new_price}

    try:
        from sp_api.api import ListingsItems
        from sp_api.base import Marketplaces, SellingApiException

        marketplace = Marketplaces.ZA  # Amazon.co.za

        listings = ListingsItems(
            credentials=CREDENTIALS,
            marketplace=marketplace,
        )

        # Build the patch request — update standardPrice attribute
        patch = {
            "productType": "PRODUCT",
            "patches": [
                {
                    "op": "replace",
                    "path": "/attributes/purchasable_offer",
                    "value": [{
                        "marketplace_id": MARKETPLACE_ID,
                        "currency": currency,
                        "our_price": [{"schedule": [{"value_with_tax": new_price}]}]
                    }]
                }
            ]
        }

        logger.info(f"SP-API: Pushing price R{new_price} for SKU={sku}")
        response = listings.patch_listings_item(
            sellerId=SELLER_ID,
            sku=sku,
            marketplaceIds=[MARKETPLACE_ID],
            body=patch,
        )

        status = response.payload.get("status", "UNKNOWN") if response.payload else "UNKNOWN"
        if status in ("ACCEPTED", "VALID"):
            logger.success(f"✅ SP-API: Price updated — SKU={sku}, Price=R{new_price}, Status={status}")
            return {"ok": True, "message": f"Price updated to R{new_price:.2f}", "sku": sku, "price": new_price, "status": status}
        else:
            issues = response.payload.get("issues", []) if response.payload else []
            msg = f"Amazon returned status: {status}"
            if issues:
                msg += f" — {issues[0].get('message', '')}"
            logger.warning(f"SP-API: Unexpected status — {msg}")
            return {"ok": False, "message": msg, "sku": sku, "price": new_price, "status": status}

    except Exception as e:
        logger.error(f"SP-API push_price error for SKU={sku}: {e}")
        return {"ok": False, "message": str(e), "sku": sku, "price": new_price}


def fetch_my_listings(limit: int = 50) -> dict:
    """
    Fetch all active listings from Amazon Seller Central via SP-API.
    Returns list of { sku, asin, price, quantity, status, title }
    """
    if not _creds_ok():
        return {"ok": False, "message": "SP-API credentials not configured", "listings": []}

    try:
        from sp_api.api import ListingsItems, CatalogItems
        from sp_api.base import Marketplaces

        marketplace = Marketplaces.ZA
        listings_api = ListingsItems(credentials=CREDENTIALS, marketplace=marketplace)

        logger.info(f"SP-API: Fetching listings for seller {SELLER_ID}")
        response = listings_api.get_listings_items(
            sellerId=SELLER_ID,
            marketplaceIds=[MARKETPLACE_ID],
            pageSize=limit,
        )

        items = []
        if response.payload and response.payload.get("items"):
            for item in response.payload["items"]:
                attrs = item.get("attributes", {})
                offer = attrs.get("purchasable_offer", [{}])[0] if attrs.get("purchasable_offer") else {}
                our_price = None
                try:
                    our_price = offer.get("our_price", [{}])[0].get("schedule", [{}])[0].get("value_with_tax")
                except Exception:
                    pass
                quantity = None
                try:
                    quantity = attrs.get("fulfillment_availability", [{}])[0].get("quantity")
                except Exception:
                    pass
                items.append({
                    "sku":       item.get("sku"),
                    "asin":      item.get("asin"),
                    "title":     (attrs.get("item_name") or [{}])[0].get("value", ""),
                    "price":     our_price,
                    "quantity":  quantity,
                    "status":    item.get("summaries", [{}])[0].get("status", "UNKNOWN"),
                })

        logger.success(f"✅ SP-API: Fetched {len(items)} listings")
        return {"ok": True, "listings": items, "count": len(items)}

    except Exception as e:
        logger.error(f"SP-API fetch_my_listings error: {e}")
        return {"ok": False, "message": str(e), "listings": []}


def get_competitive_pricing(asins: list) -> dict:
    """
    Fetch competitive pricing for a list of ASINs.
    Returns { asin: { buybox_price, lowest_price } }
    """
    if not _creds_ok():
        return {"ok": False, "message": "SP-API credentials not configured", "pricing": {}}

    try:
        from sp_api.api import ProductPricing
        from sp_api.base import Marketplaces

        marketplace = Marketplaces.ZA
        pricing_api = ProductPricing(credentials=CREDENTIALS, marketplace=marketplace)

        # SP-API allows max 20 ASINs per call
        results = {}
        for i in range(0, len(asins), 20):
            batch = asins[i:i+20]
            response = pricing_api.get_competitive_pricing_for_asins(
                asins=batch,
                marketplaceId=MARKETPLACE_ID,
            )
            if response.payload:
                for item in response.payload:
                    asin = item.get("ASIN")
                    pricing = item.get("Product", {}).get("CompetitivePricing", {})
                    prices = pricing.get("CompetitivePrices", [])
                    buybox_price = None
                    for p in prices:
                        if p.get("condition") == "New" and p.get("belongsToBuyingBox"):
                            buybox_price = p.get("Price", {}).get("ListingPrice", {}).get("Amount")
                            break
                    results[asin] = {"buybox_price": buybox_price}
            time.sleep(0.5)  # Rate limit safety

        logger.success(f"✅ SP-API: Got pricing for {len(results)} ASINs")
        return {"ok": True, "pricing": results}

    except Exception as e:
        logger.error(f"SP-API get_competitive_pricing error: {e}")
        return {"ok": False, "message": str(e), "pricing": {}}


def check_credentials() -> dict:
    """Quick credential check — tries to list 1 listing to verify keys work."""
    if not _creds_ok():
        return {"ok": False, "message": "Missing credentials — check environment variables"}
    try:
        from sp_api.api import Sellers
        from sp_api.base import Marketplaces
        sellers = Sellers(credentials=CREDENTIALS, marketplace=Marketplaces.ZA)
        response = sellers.get_marketplace_participations()
        if response.payload:
            return {"ok": True, "message": "SP-API credentials verified ✅", "seller_id": SELLER_ID}
        return {"ok": False, "message": "No marketplace participations returned"}
    except Exception as e:
        return {"ok": False, "message": f"Credential check failed: {str(e)}"}
