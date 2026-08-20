"""Kirim pesan signal langsung ke chat pribadi admin lewat Bot API (HTTP biasa, tanpa library besar)."""

import logging
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def send_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diset di .env")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code != 200:
        logger.error("Gagal kirim pesan Telegram: %s", resp.text)
    else:
        logger.info("Signal berhasil dikirim ke Telegram")
