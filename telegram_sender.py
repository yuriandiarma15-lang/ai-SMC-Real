"""Kirim pesan signal langsung ke Telegram."""

import logging
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    """
    Kirim pesan ke Telegram.

    Return:
        True  = berhasil
        False = gagal
    """

    # ==========================================
    # CEK CONFIG
    # ==========================================

    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN kosong / tidak terbaca."
        )
        return False

    if not TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_CHAT_ID kosong / tidak terbaca."
        )
        return False

    # ==========================================
    # TELEGRAM API
    # ==========================================

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:

        resp = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        # ======================================
        # SUCCESS
        # ======================================

        if resp.status_code == 200:

            data = resp.json()

            if data.get("ok"):

                logger.info(
                    "Signal berhasil dikirim ke Telegram."
                )

                return True

            logger.error(
                "Telegram API mengembalikan ok=false: %s",
                resp.text,
            )

            return False

        # ======================================
        # ERROR
        # ======================================

        logger.error(
            "Gagal kirim pesan Telegram. "
            "HTTP %s: %s",
            resp.status_code,
            resp.text,
        )

        return False

    except requests.RequestException as e:

        logger.exception(
            "Error koneksi ke Telegram: %s",
            e,
        )

        return False
