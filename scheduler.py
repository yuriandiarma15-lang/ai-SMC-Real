"""
Jadwal pengiriman signal setiap H1 close, sesuai jam operasional:
07:00 - 23:00 WIB (Senin-Sabtu) + lanjut 00:00 - 02:00 WIB (dini hari, kelanjutan sesi malam).
Detail & alasan pembagian cron ada di config.py.

Setiap signal yang berupa pending order juga otomatis dijadwalkan pengecekan
PENDING_ORDER_TIMEOUT_MINUTES kemudian, untuk auto-skip kalau belum kesentuh harga.
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
from signal_generator import generate_signal, format_signal_message
from telegram_sender import send_message
from pending_order_monitor import check_pending_order

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_scheduler: BlockingScheduler | None = None


def run_signal_job():
    logger.info("Menjalankan job signal H1...")
    try:
        signal = generate_signal()
        message = format_signal_message(signal)
        send_message(message)
        logger.info("Signal terkirim: %s @ %s (prob %s%%, order: %s)",
                     signal.bias, signal.entry_price, signal.probability, signal.order_type)

        if signal.is_pending and _scheduler is not None:
            run_at = signal.timestamp + timedelta(minutes=PENDING_ORDER_TIMEOUT_MINUTES)
            _scheduler.add_job(
                check_pending_order,
                DateTrigger(run_date=run_at, timezone=TIMEZONE),
                args=[signal.entry_price, signal.order_type, signal.timestamp],
                id=f"pending_check_{signal.timestamp.strftime('%Y%m%d_%H%M%S')}",
                misfire_grace_time=120,
            )
            logger.info("Pengecekan pending order dijadwalkan jam %s", run_at.strftime("%H:%M"))
    except Exception:
        logger.exception("Gagal generate/kirim signal")


def start():
    global _scheduler
    _scheduler = BlockingScheduler(timezone=TIMEZONE)

    hours_main = ",".join(str(h) for h in ACTIVE_HOURS_MAIN)
    _scheduler.add_job(
        run_signal_job,
        CronTrigger(day_of_week=DOW_MAIN, hour=hours_main, minute=0, timezone=TIMEZONE),
        id="signal_main_hours",
        misfire_grace_time=120,
    )

    hours_ext = ",".join(str(h) for h in ACTIVE_HOURS_EXTENDED)
    _scheduler.add_job(
        run_signal_job,
        CronTrigger(day_of_week=DOW_EXTENDED, hour=hours_ext, minute=0, timezone=TIMEZONE),
        id="signal_extended_hours",
        misfire_grace_time=120,
    )

    logger.info("Scheduler aktif. Signal akan dikirim setiap jam :00 WIB, 07:00-02:00, Senin-Sabtu.")
    _scheduler.start()


if __name__ == "__main__":
    start()
