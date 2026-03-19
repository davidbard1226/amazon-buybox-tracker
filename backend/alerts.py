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

  Daily summary:
    DAILY_SUMMARY_TIME  - e.g. "08:00" to auto-send every morning
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
    defaults = {
        "whatsapp_phone":    os.getenv("WHATSAPP_PHONE", ""),
        "callmebot_apikey":  os.getenv("CALLMEBOT_APIKEY", ""),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id":  os.getenv("TELEGRAM_CHAT_ID", ""),
        "alert_losing":  _bool_env("ALERT_LOSING",  True),
        "alert_winning": _bool_env("ALERT_WINNING", True),
        "alert_amazon":  _bool_env("ALERT_AMAZON",  True),
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                defaults.update(json.load(f))
        except Exception:
            pass
    return defaults


def save_alert_settings(settings: dict):
    """Save settings to file (runtime cache only - won't survive Render restarts)."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
        logger.info("Alert settings saved to file (runtime cache)")
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
    """Send a message via the Telegram Bot API."""
    if not bot_token or not chat_id:
        logger.warning("Telegram bot token or chat ID not configured")
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
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
# Rich message builder
# ============================================================================

def build_alert_message(alert_type: str, data: dict) -> str:
    """Build a rich Telegram/WhatsApp message with ASIN, SKU, prices and gap."""
    asin      = data.get("asin") or ""
    sku       = data.get("sku") or ""
    title     = (data.get("title") or asin)[:55]
    price     = data.get("buybox_price") or 0
    seller    = data.get("buybox_seller") or "Unknown"
    my_price  = data.get("my_price")
    min_price = data.get("min_price")
    currency  = data.get("currency") or "R"

    ref      = ("SKU: " + sku) if sku else ("ASIN: " + asin)
    my_line  = ("💰 My price:    " + currency + "{:.2f}".format(my_price)) if my_price else "💰 My price:    —"
    gap_line = ""
    if my_price and price:
        gap       = my_price - price
        direction = "above" if gap > 0 else "below"
        gap_line  = "\n📉 Gap: " + currency + "{:.2f} {} them".format(abs(gap), direction)

    if alert_type == "losing":
        return (
            "🔴 <b>BuyBox LOST!</b>\n"
            + title + "\n"
            + "🔖 " + ref + "\n\n"
            + my_line + "\n"
            + "🏷 Their price: " + currency + "{:.2f}".format(price)
            + gap_line + "\n"
            + "🛒 Seller: " + seller
        )
    elif alert_type == "winning":
        return (
            "🟢 <b>BuyBox WON!</b>\n"
            + title + "\n"
            + "🔖 " + ref + "\n\n"
            + my_line + "\n"
            + "✅ We hold the BuyBox"
        )
    elif alert_type == "amazon":
        return (
            "🟡 <b>Amazon Took BuyBox</b>\n"
            + title + "\n"
            + "🔖 " + ref + "\n\n"
            + "🏷 Amazon price: " + currency + "{:.2f}".format(price) + "\n"
            + my_line
        )
    elif alert_type == "win_at_loss":
        min_str = (currency + "{:.2f}".format(min_price)) if min_price else "—"
        return (
            "⚠️ <b>Winning at a LOSS!</b>\n"
            + title + "\n"
            + "🔖 " + ref + "\n\n"
            + my_line + "\n"
            + "🔻 Min floor:  " + min_str + "\n"
            + "📉 Selling below min price — update needed!"
        )
    return ""


# ============================================================================
# Unified alert dispatcher
# ============================================================================

def check_and_alert(old_status: str, new_data: dict):
    """Check for buybox status change and win-at-loss, then fire alerts."""
    settings   = load_alert_settings()
    new_status = new_data.get("buybox_status", "unknown")
    my_price   = new_data.get("my_price")
    min_price  = new_data.get("min_price")

    message = None

    # Win-at-loss: winning but price is below min viable floor
    if new_status == "winning" and my_price and min_price and my_price < min_price:
        message = build_alert_message("win_at_loss", new_data)

    elif old_status != new_status:
        if new_status == "losing" and settings.get("alert_losing"):
            message = build_alert_message("losing", new_data)
        elif new_status == "winning" and settings.get("alert_winning") and old_status != "winning":
            message = build_alert_message("winning", new_data)
        elif new_status == "amazon" and settings.get("alert_amazon"):
            message = build_alert_message("amazon", new_data)

    if not message:
        return

    phone     = settings.get("whatsapp_phone", "")
    apikey    = settings.get("callmebot_apikey", "")
    bot_token = settings.get("telegram_bot_token", "")
    chat_id   = settings.get("telegram_chat_id", "")

    if phone and apikey:
        send_whatsapp_alert(phone, apikey, message)
    if bot_token and chat_id:
        send_telegram_alert(bot_token, chat_id, message)


# ============================================================================
# Daily Intelligence Summary
# ============================================================================

def send_daily_summary(products: list, history: list) -> bool:
    """Build and send a daily intelligence summary via Telegram."""
    settings  = load_alert_settings()
    bot_token = settings.get("telegram_bot_token", "")
    chat_id   = settings.get("telegram_chat_id", "")
    if not bot_token or not chat_id:
        logger.warning("Telegram not configured — skipping daily summary")
        return False

    from datetime import datetime, timedelta
    from collections import Counter

    wins       = [p for p in products if p.get("buybox_status") == "winning"]
    losses     = [p for p in products if p.get("buybox_status") == "losing"]
    amazon     = [p for p in products if p.get("buybox_status") == "amazon"]
    win_at_loss = [
        p for p in wins
        if p.get("my_price") and p.get("min_price") and p["my_price"] < p["min_price"]
    ]

    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent = [
        h for h in history
        if h.get("timestamp") and (
            h["timestamp"] > cutoff if isinstance(h["timestamp"], datetime)
            else False
        )
    ]
    seller_counts = Counter(
        h["seller"] for h in recent
        if h.get("seller") and h["seller"] != "Bonolo Online"
    )
    top_competitors = seller_counts.most_common(5)
    asin_counts     = Counter(h["asin"] for h in recent if h.get("asin"))
    top_volatile    = asin_counts.most_common(5)
    asin_map        = {p["asin"]: (p.get("sku") or (p.get("title") or "")[:25]) for p in products}

    now     = datetime.now()
    datestr = now.strftime("%A, %d %B %Y")

    msg = (
        "📊 <b>Amazon BuyBox Daily Summary</b>\n"
        + datestr + "\n\n"
        + "🏆 <b>Performance</b>\n"
        + "✅ Winning: " + str(len(wins))
        + "  ❌ Losing: " + str(len(losses))
        + "  🛒 Amazon: " + str(len(amazon)) + "\n"
        + "📦 Total tracked: " + str(len(products)) + "\n"
        + "📉 Price changes (24h): " + str(len(recent)) + "\n"
    )

    if win_at_loss:
        msg += "\n⚠️ <b>Winning at a LOSS: " + str(len(win_at_loss)) + " products</b>\n"
        for p in win_at_loss[:5]:
            ref = p.get("sku") or p.get("asin") or ""
            mp  = p.get("my_price") or 0
            mn  = p.get("min_price") or 0
            msg += "  • [" + ref + "] R{:.0f} &lt; min R{:.0f}\n".format(mp, mn)

    if top_competitors:
        msg += "\n🔥 <b>Top Competitors (24h)</b>\n"
        for i, (seller, count) in enumerate(top_competitors, 1):
            msg += "  " + str(i) + ". " + seller + " — " + str(count) + " changes\n"

    if top_volatile:
        msg += "\n🌡 <b>Most Volatile ASINs (24h)</b>\n"
        for i, (asin, count) in enumerate(top_volatile, 1):
            ref = asin_map.get(asin, asin)
            msg += "  " + str(i) + ". [" + asin + "] " + ref[:20] + " — " + str(count) + " changes\n"

    msg += "\n🕐 " + now.strftime("%H:%M") + " SAST"

    return send_telegram_alert(bot_token, chat_id, msg)
