"""
Alerts - WhatsApp (via CallMeBot) and Telegram Bot

NOTE on Render.com: The filesystem is ephemeral, so alert_settings.json
won't persist across deploys/restarts. Settings are loaded from environment
variables as the source of truth. When saved via the API, they are written
to a file as a runtime cache only (lasts until next restart).

Set these environment variables on Render for persistent alerts:

  WhatsApp (CallMeBot):
    WHATSAPP_PHONE      - Your WhatsApp number with country code (e.g. +27821234567)
    CALLMEBOT_APIKEY    - Your CallMeBot API key

  Telegram:
    TELEGRAM_BOT_TOKEN  - Bot token from @BotFather (e.g. 123456:ABC-DEF...)
    TELEGRAM_CHAT_ID    - Your chat/group ID (e.g. 123456789 or -100123456789)

  Alert toggles (apply to both channels):
    ALERT_LOSING        - true/false (default: true)
    ALERT_WINNING       - true/false (default: true)
    ALERT_AMAZON        - true/false (default: true)

How to get your Telegram bot token & chat ID:
  1. Open Telegram and search for @BotFather
  2. Send /newbot and follow the prompts - BotFather gives you the token
  3. Start a chat with your new bot (or add it to a group)
  4. Visit: https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
     and look for "id" inside the "chat" object - that is your TELEGRAM_CHAT_ID
"""
import os
import json
import requests
from loguru import logger

SETTINGS_FILE = "alert_settings.json"

def _bool_env(key: str, default: bool = True) -> bool:
    val = os.getenv(key, "").lower()
    if val in ("false", "0", "no"):
        return False
    if val in ("true", "1", "yes"):
        return True
    return default

def load_alert_settings() -> dict:
    """Load settings: env vars are the primary source, file is a runtime override."""
    # Start with env-var defaults (always available, survive restarts)
    defaults = {
        # WhatsApp
        "whatsapp_phone": os.getenv("WHATSAPP_PHONE", ""),
        "callmebot_apikey": os.getenv("CALLMEBOT_APIKEY", ""),
        # Telegram
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        # Alert toggles (shared by both channels)
        "alert_losing": _bool_env("ALERT_LOSING", True),
        "alert_winning": _bool_env("ALERT_WINNING", True),
        "alert_amazon": _bool_env("ALERT_AMAZON", True),
    }
    # If a runtime file exists (set during this session via API), merge it on top
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                file_settings = json.load(f)
            # File overrides env vars only for keys that are actually set in the file
            defaults.update(file_settings)
        except Exception:
            pass
    return defaults

def save_alert_settings(settings: dict):
    """Save settings to file (runtime cache only - won't survive Render restarts).
    
    For persistent settings, set env vars directly in the Render dashboard:
      WhatsApp: WHATSAPP_PHONE, CALLMEBOT_APIKEY
      Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    """
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        logger.info("Alert settings saved to file (runtime cache)")
        logger.warning(
            "⚠️  These settings will reset on next Render restart. "
            "Set WHATSAPP_PHONE/CALLMEBOT_APIKEY and TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
            "as Render env vars for persistence."
        )
    except Exception as e:
        logger.error(f"Could not save alert settings file: {e}")

# ============================================================================
# WhatsApp via CallMeBot
# ============================================================================

def send_whatsapp_alert(phone: str, apikey: str, message: str) -> bool:
    if not phone or not apikey:
        logger.warning("WhatsApp phone or API key not configured")
        return False
    try:
        url = "https://api.callmebot.com/whatsapp.php"
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

# ============================================================================
# Telegram Bot API
# ============================================================================

def send_telegram_alert(bot_token: str, chat_id: str, message: str) -> bool:
    """Send a message via the Telegram Bot API using plain HTTPS (no extra libs needed)."""
    if not bot_token or not chat_id:
        logger.warning("Telegram bot token or chat ID not configured")
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",   # supports <b>, <i>, <code> tags
        }
        r = requests.post(url, json=payload, timeout=10)
        data = r.json()
        if r.status_code == 200 and data.get("ok"):
            logger.success(f"Telegram alert sent to chat {chat_id}")
            return True
        else:
            logger.error(f"Telegram API error: {r.status_code} - {data.get('description', r.text[:100])}")
            return False
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}")
        return False

# ============================================================================
# Unified alert dispatcher
# ============================================================================

def check_and_alert(old_status: str, new_data: dict):
    """Check for a buybox status change and fire alerts on all configured channels."""
    settings = load_alert_settings()
    new_status = new_data.get("buybox_status", "unknown")

    if old_status == new_status:
        return

    asin = new_data.get("asin", "")
    title = new_data.get("title", asin)[:40]
    price = new_data.get("buybox_price", 0)
    seller = new_data.get("buybox_seller", "Unknown")
    currency = new_data.get("currency", "R")

    message = None
    if new_status == "losing" and settings.get("alert_losing"):
        message = (
            f"🔴 LOSING BUYBOX\n"
            f"{title}\n"
            f"ASIN: {asin}\n"
            f"Price: {currency}{price}\n"
            f"Winner: {seller}"
        )
    elif new_status == "winning" and settings.get("alert_winning") and old_status != "winning":
        message = (
            f"🟢 YOU WON BUYBOX\n"
            f"{title}\n"
            f"ASIN: {asin}\n"
            f"Price: {currency}{price}"
        )
    elif new_status == "amazon" and settings.get("alert_amazon"):
        message = (
            f"🟡 AMAZON TOOK BUYBOX\n"
            f"{title}\n"
            f"ASIN: {asin}\n"
            f"Price: {currency}{price}"
        )

    if not message:
        return

    # WhatsApp channel
    phone = settings.get("whatsapp_phone", "")
    apikey = settings.get("callmebot_apikey", "")
    if phone and apikey:
        send_whatsapp_alert(phone, apikey, message)

    # Telegram channel
    bot_token = settings.get("telegram_bot_token", "")
    chat_id = settings.get("telegram_chat_id", "")
    if bot_token and chat_id:
        send_telegram_alert(bot_token, chat_id, message)
