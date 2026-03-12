"""
Amazon SP-API Client — Pure raw HTTP, NO python-amazon-sp-api library.
All auth done manually: LWA token exchange + AWS SigV4 signing.
"""
import os, hmac, hashlib, json, urllib.parse
import requests as req
from datetime import datetime, timezone
from loguru import logger

# ── Read credentials fresh from env every call ───────────────
def _r(key): return os.getenv(key, "")

def _creds_ok() -> bool:
    missing = [k for k in [
        "LWA_CLIENT_ID","LWA_CLIENT_SECRET","LWA_REFRESH_TOKEN",
        "AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY","SP_API_SELLER_ID"
    ] if not _r(k)]
    if missing:
        logger.error(f"SP-API missing env vars: {missing}")
        return False
    return True

# ── Step 1: Exchange refresh token → access token ────────────
def _get_access_token() -> str:
    resp = req.post("https://api.amazon.com/auth/o2/token", data={
        "grant_type":    "refresh_token",
        "refresh_token": _r("LWA_REFRESH_TOKEN"),
        "client_id":     _r("LWA_CLIENT_ID"),
        "client_secret": _r("LWA_CLIENT_SECRET"),
    }, timeout=15)
    if resp.status_code != 200:
        raise Exception(f"LWA token exchange failed {resp.status_code}: {resp.text}")
    return resp.json()["access_token"]

# ── Step 2: AWS SigV4 signing ─────────────────────────────────
def _sign(method: str, url: str, body: str, access_token: str) -> dict:
    aws_key    = _r("AWS_ACCESS_KEY_ID")
    aws_secret = _r("AWS_SECRET_ACCESS_KEY")
    region     = "eu-west-1"
    service    = "execute-api"

    now        = datetime.now(timezone.utc)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    parsed     = urllib.parse.urlparse(url)
    host       = parsed.netloc
    uri        = urllib.parse.quote(parsed.path, safe="/-._~")
    qs         = parsed.query

    payload_hash    = hashlib.sha256(body.encode()).hexdigest()
    canonical_hdrs  = f"host:{host}\nx-amz-access-token:{access_token}\nx-amz-date:{amz_date}\n"
    signed_hdrs     = "host;x-amz-access-token;x-amz-date"
    canonical_req   = f"{method}\n{uri}\n{qs}\n{canonical_hdrs}\n{signed_hdrs}\n{payload_hash}"

    cred_scope      = f"{date_stamp}/{region}/{service}/aws4_request"
    str_to_sign     = f"AWS4-HMAC-SHA256\n{amz_date}\n{cred_scope}\n{hashlib.sha256(canonical_req.encode()).hexdigest()}"

    def _hmac(key, msg):
        return hmac.new(key if isinstance(key, bytes) else key.encode(), msg.encode(), hashlib.sha256).digest()

    signing_key = _hmac(_hmac(_hmac(_hmac(f"AWS4{aws_secret}", date_stamp), region), service), "aws4_request")
    signature   = hmac.new(signing_key, str_to_sign.encode(), hashlib.sha256).hexdigest()
    auth        = (f"AWS4-HMAC-SHA256 Credential={aws_key}/{cred_scope}, "
                   f"SignedHeaders={signed_hdrs}, Signature={signature}")

    return {
        "host":               host,
        "x-amz-access-token": access_token,
        "x-amz-date":         amz_date,
        "Authorization":      auth,
        "Content-Type":       "application/json",
    }

# ── push_price ────────────────────────────────────────────────
def push_price(sku: str, new_price: float, currency: str = "ZAR") -> dict:
    if not _creds_ok():
        return {"ok": False, "message": "SP-API credentials not configured", "sku": sku, "price": new_price}
    if not sku or not new_price or new_price <= 0:
        return {"ok": False, "message": "Invalid SKU or price", "sku": sku, "price": new_price}

    seller_id = _r("SP_API_SELLER_ID")
    market_id = _r("SP_API_MARKETPLACE_ID") or "A1E5JOF6FQYU90"

    try:
        logger.info(f"SP-API push_price: getting access token for SKU={sku}")
        token = _get_access_token()
        logger.info(f"SP-API push_price: got access token, pushing R{new_price} for SKU={sku}")

        patch = {
            "productType": "PRODUCT",
            "patches": [{
                "op":   "replace",
                "path": "/attributes/purchasable_offer",
                "value": [{
                    "marketplace_id": market_id,
                    "currency":       currency,
                    "our_price":      [{"schedule": [{"value_with_tax": new_price}]}]
                }]
            }]
        }
        body    = json.dumps(patch)
        sku_enc = urllib.parse.quote(sku, safe="")
        url     = (f"https://sellingpartnerapi-eu.amazon.com"
                   f"/listings/2021-08-01/items/{seller_id}/{sku_enc}"
                   f"?marketplaceIds={market_id}")

        headers  = _sign("PATCH", url, body, token)
        response = req.patch(url, headers=headers, data=body, timeout=20)

        logger.info(f"SP-API response {response.status_code}: {response.text[:300]}")

        if response.status_code in (200, 202):
            status = response.json().get("status", "ACCEPTED")
            return {"ok": True, "message": f"Price updated to R{new_price:.2f}", "sku": sku, "price": new_price, "status": status}

        errors = response.json().get("errors", [])
        msg    = errors[0].get("message", response.text[:200]) if errors else response.text[:200]
        return {"ok": False, "message": f"{response.status_code}: {msg}", "sku": sku, "price": new_price}

    except Exception as e:
        logger.error(f"SP-API push_price error SKU={sku}: {e}")
        return {"ok": False, "message": str(e), "sku": sku, "price": new_price}


# ── check_credentials ─────────────────────────────────────────
def check_credentials() -> dict:
    if not _creds_ok():
        return {"ok": False, "message": "Missing env vars"}
    try:
        token     = _get_access_token()
        seller_id = _r("SP_API_SELLER_ID")
        market_id = _r("SP_API_MARKETPLACE_ID") or "A1E5JOF6FQYU90"
        url       = f"https://sellingpartnerapi-eu.amazon.com/sellers/v1/marketplaceParticipations"
        headers   = _sign("GET", url, "", token)
        resp      = req.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return {"ok": True, "message": "SP-API credentials verified ✅", "seller_id": seller_id}
        return {"ok": False, "message": f"{resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ── fetch_my_listings (stub — returns empty, not used actively) ──
def fetch_my_listings(limit: int = 50) -> dict:
    return {"ok": True, "listings": [], "count": 0, "message": "Use sync-listings endpoint"}


# ── get_competitive_pricing (stub) ───────────────────────────
def get_competitive_pricing(asins: list) -> dict:
    return {"ok": True, "pricing": {}, "message": "Not implemented in raw HTTP version"}
