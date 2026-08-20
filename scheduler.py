"""
Jadwal pengiriman signal setiap H1 close.

Jam aktif:
07:00 - 23:00 WIB
00:00 - 02:00 WIB

Signal dibuat dari:
M5 -> struktur SMC
M1 -> timing entry

Pending order:
Jika signal berupa pending order, akan dicek kembali
setelah PENDING_ORDER_TIMEOUT_MINUTES.
"""

import logging
from datetime import timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from config import (
    TIMEZONE,
    ACTIVE_HOURS_MAIN,
    ACTIVE_HOURS_EXTENDED,
    DOW_MAIN,
    DOW_EXTENDED,
    PENDING_ORDER_TIMEOUT_MINUTES,
)

from signal_generator import (
    generate_signal,
    format_signal_message,
)

from telegram_sender import send_message

from pending_order_monitor import check_pending_order


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


# =========================================================
# SCHEDULER
# =========================================================

_scheduler: BlockingScheduler | None = None


# =========================================================
# RUN SIGNAL
# =========================================================

def run_signal_job():

    logger.info(
        "Menjalankan job signal H1..."
    )

    try:

        # =================================================
        # GENERATE SIGNAL
        # =================================================

        signal = generate_signal()

        logger.info(
            "Signal berhasil dianalisa: "
            "%s @ %s | probability=%s%% | order=%s",
            signal.bias,
            signal.entry_price,
            signal.probability,
            signal.order_type,
        )

        # =================================================
        # FORMAT MESSAGE
        # =================================================

        message = format_signal_message(
            signal
        )

        # =================================================
        # SEND TELEGRAM
        # =================================================

        sent = send_message(
            message
        )

        # =================================================
        # CEK HASIL PENGIRIMAN
        # =================================================

        if sent:

            logger.info(
                "Signal TERKIRIM ke Telegram: "
                "%s @ %s | prob %s%% | order=%s",
                signal.bias,
                signal.entry_price,
                signal.probability,
                signal.order_type,
            )

        else:

            logger.error(
                "Signal GAGAL DIKIRIM ke Telegram: "
                "%s @ %s",
                signal.bias,
                signal.entry_price,
            )

            # Jangan lanjut membuat monitoring
            # pending order kalau signal bahkan
            # tidak berhasil dikirim.
            return

        # =================================================
        # PENDING ORDER MONITOR
        # =================================================

        if (
            signal.is_pending
            and _scheduler is not None
        ):

            run_at = (
                signal.timestamp
                + timedelta(
                    minutes=PENDING_ORDER_TIMEOUT_MINUTES
                )
            )

            job_id = (
                "pending_check_"
                + signal.timestamp.strftime(
                    "%Y%m%d_%H%M%S"
                )
            )

            _scheduler.add_job(

                check_pending_order,

                DateTrigger(
                    run_date=run_at,
                    timezone=TIMEZONE,
                ),

                args=[
                    signal.entry_price,
                    signal.order_type,
                    signal.timestamp,
                ],

                id=job_id,

                misfire_grace_time=120,
            )

            logger.info(
                "Pengecekan pending order "
                "dijadwalkan jam %s",
                run_at.strftime("%H:%M"),
            )

    except Exception:

        logger.exception(
            "Gagal generate/kirim signal"
        )


# =========================================================
# START SCHEDULER
# =========================================================

def start():

    global _scheduler

    _scheduler = BlockingScheduler(
        timezone=TIMEZONE
    )

    # =====================================================
    # MAIN HOURS
    # 07:00 - 23:00
    # =====================================================

    hours_main = ",".join(
        str(h)
        for h in ACTIVE_HOURS_MAIN
    )

    _scheduler.add_job(

        run_signal_job,

        CronTrigger(

            day_of_week=DOW_MAIN,

            hour=hours_main,

            minute=0,

            timezone=TIMEZONE,
        ),

        id="signal_main_hours",

        misfire_grace_time=120,
    )

    # =====================================================
    # EXTENDED HOURS
    # 00:00 - 02:00
    # =====================================================

    hours_ext = ",".join(
        str(h)
        for h in ACTIVE_HOURS_EXTENDED
    )

    _scheduler.add_job(

        run_signal_job,

        CronTrigger(

            day_of_week=DOW_EXTENDED,

            hour=hours_ext,

            minute=0,

            timezone=TIMEZONE,
        ),

        id="signal_extended_hours",

        misfire_grace_time=120,
    )

    # =====================================================
    # LOG
    # =====================================================

    logger.info(
        "Scheduler aktif. "
        "Signal akan dikirim setiap jam :00 WIB, "
        "07:00-02:00, Senin-Sabtu."
    )

    # =====================================================
    # START
    # =====================================================

    _scheduler.start()


# =========================================================
# DIRECT RUN
# =========================================================

if __name__ == "__main__":
    start()
