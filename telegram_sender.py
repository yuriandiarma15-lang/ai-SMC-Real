"""Kirim pesan signal langsung ke Telegram."""

import logging
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def send_message(text: str) -> bool:
    """
    Kirim pesan ke Telegram.

    True  = berhasil
    False = gagal
    """

    # ==========================================
    # CEK TOKEN & CHAT ID
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

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        # ======================================
        # BERHASIL
        # ======================================

        if response.status_code == 200:

            data = response.json()

            if data.get("ok"):

                logger.info(
                    "Signal berhasil dikirim ke Telegram."
                )

                return True

            logger.error(
                "Telegram API menolak pesan: %s",
                response.text,
            )

            return False

        # ======================================
        # GAGAL
        # ======================================

        logger.error(
            "Gagal kirim pesan Telegram. "
            "HTTP %s: %s",
            response.status_code,
            response.text,
        )

        return False

    except requests.RequestException as e:

        logger.exception(
            "Koneksi ke Telegram gagal: %s",
            e,
        )

        return False
