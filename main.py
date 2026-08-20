"""
Entry point utama.

Normal:
    python main.py

Test scheduler:
    python main.py --test

Bot menjalankan:
- Telegram polling
- /start
- /signal
- APScheduler otomatis
"""

import sys
import time
import threading
import logging
import requests

from config import TELEGRAM_BOT_TOKEN

from scheduler import (
    start,
    run_signal_job,
)

from signal_generator import (
    generate_signal,
    format_signal_message,
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "[%(levelname)s] "
        "%(name)s: "
        "%(message)s"
    ),
)

logger = logging.getLogger(
    "telegram_bot"
)


# =========================================================
# TELEGRAM API
# =========================================================

TELEGRAM_API = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
)

# =========================================================
# SEND MESSAGE
# =========================================================

def send_telegram_message(
    chat_id: int,
    text: str,
):

    try:

        response = requests.post(

            f"{TELEGRAM_API}/sendMessage",

            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },

            timeout=30,
        )

        data = response.json()

        if not data.get("ok"):

            logger.error(
                "Telegram sendMessage error: %s",
                data,
            )

    except Exception:

        logger.exception(
            "Gagal mengirim pesan Telegram"
        )


# =========================================================
# HANDLE UPDATE
# =========================================================

def handle_update(
    update: dict,
):

    message = update.get(
        "message"
    )

    if not message:
        return

    text = message.get(
        "text",
        "",
    ).strip()

    if not text:
        return

    chat = message.get(
        "chat"
    )

    if not chat:
        return

    chat_id = chat["id"]

    # =====================================================
    # START
    # =====================================================

    if text.startswith(
        "/start"
    ):

        reply = (

            "🤖 *XAU AI INTELLIGENCE*\n"
            "\n"
            "Bot berhasil aktif.\n"
            "\n"
            "Gunakan:\n"
            "👉 `/signal`\n"
            "\n"
            "untuk mendapatkan analisa "
            "XAUUSD berdasarkan "
            "12 candle M5 sebelumnya."
        )

        send_telegram_message(
            chat_id,
            reply,
        )

        logger.info(
            "/start dari chat_id=%s",
            chat_id,
        )

        return

    # =====================================================
    # SIGNAL
    # =====================================================

    if text.startswith(
        "/signal"
    ):

        logger.info(
            "/signal dari chat_id=%s",
            chat_id,
        )

        # -------------------------------------------------
        # LOADING
        # -------------------------------------------------

        send_telegram_message(

            chat_id,

            "⏳ *Menganalisa XAUUSD...*\n"
            "\n"
            "🧠 Mengambil "
            "12 candle M5 sebelumnya..."
        )

        try:

            # ---------------------------------------------
            # ANALISA 12 CANDLE M5
            # ---------------------------------------------

            signal = generate_signal(
                structure_candle_count=12
            )

            # ---------------------------------------------
            # FORMAT ASLI
            # ---------------------------------------------

            message_text = (
                format_signal_message(
                    signal
                )
            )

            # ---------------------------------------------
            # KIRIM
            # ---------------------------------------------

            send_telegram_message(
                chat_id,
                message_text,
            )

            logger.info(

                "Manual signal berhasil: "
                "%s @ %s | probability=%s%%",

                signal.bias,

                signal.entry_price,

                signal.probability,
            )

        except Exception as e:

            logger.exception(
                "Gagal memproses /signal"
            )

            send_telegram_message(

                chat_id,

                "❌ *Gagal melakukan analisa.*\n"
                "\n"
                f"`{str(e)}`\n"
                "\n"
                "Silakan coba `/signal` "
                "beberapa saat lagi.",
            )

        return


# =========================================================
# TELEGRAM POLLING
# =========================================================

def telegram_polling():

    logger.info(
        "Telegram polling dimulai."
    )

    offset = None

    while True:

        try:

            params = {
                "timeout": 30,
            }

            if offset is not None:

                params[
                    "offset"
                ] = offset

            response = requests.get(

                f"{TELEGRAM_API}/getUpdates",

                params=params,

                timeout=40,
            )

            data = response.json()

            if not data.get("ok"):

                logger.error(
                    "Telegram getUpdates error: %s",
                    data,
                )

                time.sleep(5)

                continue

            updates = data.get(
                "result",
                [],
            )

            for update in updates:

                offset = (
                    update["update_id"]
                    + 1
                )

                try:

                    handle_update(
                        update
                    )

                except Exception:

                    logger.exception(
                        "Error memproses "
                        "update Telegram"
                    )

        except requests.exceptions.Timeout:

            # Timeout long polling
            # adalah normal.

            continue

        except Exception:

            logger.exception(
                "Telegram polling error"
            )

            time.sleep(5)


# =========================================================
# START ALL
# =========================================================

def start_all():

    # =====================================================
    # SCHEDULER
    # =====================================================

    scheduler_thread = threading.Thread(

        target=start,

        name="scheduler-thread",

        daemon=True,
    )

    scheduler_thread.start()

    logger.info(
        "Scheduler thread berhasil dimulai."
    )

    # =====================================================
    # TELEGRAM
    # =====================================================

    telegram_polling()


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    # -----------------------------------------------------
    # TEST
    # -----------------------------------------------------

    if "--test" in sys.argv:

        logger.info(
            "Menjalankan test signal..."
        )

        run_signal_job()

    # -----------------------------------------------------
    # NORMAL BOT
    # -----------------------------------------------------

    else:

        start_all()
