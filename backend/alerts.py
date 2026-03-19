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

def build_alert_message(alert_type: str, new_data: dict, old_status: str = None) -> str:
    """Build a rich alert message with ASIN, SKU, my price, gap, and repriced info."""
    asin      = new_data.get("asin", "")
    sku       = new_data.get("sku", "") or ""
    title     = (new_data.get("title") or asin)[:55]
    price     = new_data.get("buybox_price") or 0
    seller    = new_data.get("buybox_seller") or "Unknown"
    my_price  = new_data.get("my_price")
    min_price = new_data.get("min_price")
    currency  = new_data.get("currency") or "R"

    ref       = f"SKU: {sku}" if sku else f"ASIN: {asin}"
    my_line   = f"💰 My price:    {currency}{my_price:.2f}" if my_price else "💰 My price:    —"
    gap_line  = ""
    if my_price and price:
        gap      = my_price - price
        direction = "above" if gap > 0 else "below"
        gap_line  = f"\n📉 Gap: {currency}{abs(gap):.2f} {direction} them"

    if alert_type == "losing":
        return (
            f"🔴 <b>BuyBox LOST!</b>\n"
            f"{title}\n"
            f"🔖 {ref}\n\n"
            f"{my_line}\n"
            f"🏷 Their price: {currency}{price:.2f}"
            f"{gap_line}\n"
            f"🛒 Seller: {seller}"
        )
    elif alert_type == "winning":
        return (
            f"🟢 <b>BuyBox WON!</b>\n"
            f"{title}\n"
            f"🔖 {ref}\n\n"
            f"{my_line}\n"
            f"✅ We hold the BuyBox"
        )
    elif alert_type == "amazon":
        return (
            f"🟡 <b>Amazon Took BuyBox</b>\n"
            f"{title}\n"
            f"🔖 {ref}\n\n"
            f"🏷 Amazon price: {currency}{price:.2f}\n"
            f"{my_line}"
        )
    elif alert_type == "win_at_loss":
        min_str = f"{currency}{min_price:.2f}" if min_price else "—"
        return (
            f"⚠️ <b>Winning at a LOSS!</b>\n"
            f"{title}\n"
            f"🔖 {ref}\n\n"
            f"{my_line}\n"
            f"🔻 Min floor:  {min_str}\n"
            f"📉 Selling below min price — needs price update!"
        )
    return ""


def check_and_alert(old_status: str, new_data: dict):
    """Check for a buybox status change and fire alerts on all configured channels."""
    settings   = load_alert_settings()
    new_status = new_data.get("buybox_status", "unknown")
    my_price   = new_data.get("my_price")
    min_price  = new_data.get("min_price")

    message = None

    # Win-at-loss check: winning but selling below min viable price
    if new_status == "winning" and my_price and min_price and my_price < min_price:
        message = build_alert_message("win_at_loss", new_data)

    elif old_status != new_status:
        if new_status == "losing" and settings.get("alert_losing"):
            message = build_alert_message("losing", new_data, old_status)
        elif new_status == "winning" and settings.get("alert_winning") and old_status != "winning":
            message = build_alert_message("winning", new_data, old_status)
        elif new_status == "amazon" and settings.get("alert_amazon"):
            message = build_alert_message("amazon", new_data, old_status)

    if not message:
        return

    # WhatsApp channel
    phone  = settings.get("whatsapp_phone", "")
    apikey = settings.get("callmebot_apikey", "")
    if phone and apikey:
        send_whatsapp_alert(phone, apikey, message)

    # Telegram channel
    bot_token = settings.get("telegram_bot_token", "")
    chat_id   = settings.get("telegram_chat_id", "")
    if bot_token and chat_id:
        send_telegram_alert(bot_token, chat_id, message)


def send_daily_summary(products: list, price_history: list) -> bool:
    """Build and send a daily intelligence summary via Telegram."""
    settings  = load_alert_settings()
    bot_token = settings.get("telegram_bot_token", "")
    chat_id   = settings.get("telegram_chat_id", "")
    if not bot_token or not chat_id:
        logger.warning("Telegram not configured — skipping daily summary")
        return False

    from datetime import datetime, timedelta
    from collections import Counter

    wins    = [p for p in products if p.get("buybox_status") == "winning"]
    losses  = [p for p in products if p.get("buybox_status") == "losing"]
    amazon  = [p for p in products if p.get("buybox_status") == "amazon"]

    # Win-at-loss
    win_at_loss = [
        p for p in wins
        if p.get("my_price") and p.get("min_price") and p["my_price"] < p["min_price"]
    ]

    # Competitor frequency from recent price history (last 24h)
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent = [h for h in price_history if h.get("timestamp") and h["timestamp"] > cutoff]
    seller_counts = Counter(h["seller"] for h in recent if h.get("seller") and h["seller"] != "BonoloOnline")
    top_competitors = seller_counts.most_common(5)

    # Most volatile ASINs
    asin_counts = Counter(h["asin"] for h in recent)
    top_volatile = asin_counts.most_common(5)
    asin_map = {p["asin"]: p.get("sku") or p.get("title", "")[:30] for p in products}

    now     = datetime.now()
    datestr = now.strftime("%A, %d %B %Y")

    msg = (
        f"📊 <b>Amazon BuyBox Daily Summary</b>\n"
        f"{datestr}\n\n"
        f"🏆 <b>Performance</b>\n"
        f"✅ Winning: {len(wins)}  ❌ Losing: {len(losses)}  🛒 Amazon: {len(amazon)}\n"
        f"📦 Total tracked: {len(products)}\n"
        f"📉 Price changes (24h): {len(recent)}\n"
    )

    if win_at_loss:
        msg += f"\n⚠️ <b>Winning at a LOSS: {len(win_at_loss)} products</b>\n"
        for p in win_at_loss[:5]:
            ref = p.get("sku") or p.get("asin", "")
            msg += f"  • [{ref}] R{p.get('my_price',0):.0f} &lt; min R{p.get('min_price',0):.0f}\n"

    if top_competitors:
        msg += "\n🔥 <b>Top Competitors (24h)</b>\n"
        for i, (seller, count) in enumerate(top_competitors, 1):
            msg += f"  {i}. {seller} — {count} changes\n"

    if top_volatile:
        msg += "\n🌡 <b>Most Volatile ASINs (24h)</b>\n"
        for i, (asin, count) in enumerate(top_volatile, 1):
            ref = asin_map.get(asin, asin)
            msg += f"  {i}. [{asin}] {ref[:25]} — {count} changes\n"

    msg += f"\n🕐 {now.strftime('%H:%M')} SAST"

    return send_telegram_alert(bot_token, chat_id, msg)
