"""
WhatsApp Alerts via CallMeBot - Free service
"""
import os
import json
import requests
from loguru import logger

SETTINGS_FILE = "alert_settings.json"

def load_alert_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "whatsapp_phone": os.getenv("WHATSAPP_PHONE", ""),
        "callmebot_apikey": os.getenv("CALLMEBOT_APIKEY", ""),
        "alert_losing": True,
        "alert_winning": True,
        "alert_amazon": True,
    }

def save_alert_settings(settings: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def send_whatsapp_alert(phone: str, apikey: str, message: str) -> bool:
    if not phone or not apikey:
        logger.warning("WhatsApp phone or API key not configured")
        return False
    try:
        url = f"https://api.callmebot.com/whatsapp.php"
        params = {"phone": phone, "text": message, "apikey": apikey}
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200 and "Message queued" in r.text:
            logger.success(f"WhatsApp alert sent to {phone}")
            return True
        else:
            logger.error(f"CallMeBot error: {r.status_code} - {r.text[:100]}")
            return False
    except Exception as e:
        logger.error(f"WhatsApp alert failed: {e}")
        return False

def check_and_alert(old_status: str, new_data: dict):
    settings = load_alert_settings()
    phone = settings.get("whatsapp_phone", "")
    apikey = settings.get("callmebot_apikey", "")
    if not phone or not apikey:
        return
    new_status = new_data.get("buybox_status", "unknown")
    asin = new_data.get("asin", "")
    title = new_data.get("title", asin)[:40]
    price = new_data.get("buybox_price", 0)
    seller = new_data.get("buybox_seller", "Unknown")
    currency = new_data.get("currency", "R")
    if old_status == new_status:
        return
    message = None
    if new_status == "losing" and settings.get("alert_losing"):
        message = f"LOSING BUYBOX - {title}\nASIN: {asin}\nPrice: {currency}{price}\nWinner: {seller}"
    elif new_status == "winning" and settings.get("alert_winning") and old_status != "winning":
        message = f"YOU WON BUYBOX - {title}\nASIN: {asin}\nPrice: {currency}{price}"
    elif new_status == "amazon" and settings.get("alert_amazon"):
        message = f"AMAZON TOOK BUYBOX - {title}\nASIN: {asin}\nPrice: {currency}{price}"
    if message:
        send_whatsapp_alert(phone, apikey, message)
