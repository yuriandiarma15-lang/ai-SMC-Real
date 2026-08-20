"""
Cek status pending order beberapa menit setelah signal dikirim (default 20 menit,
lihat PENDING_ORDER_TIMEOUT_MINUTES di config.py).

- Kalau harga M1 sudah pernah menyentuh entry_price sejak signal dibuat -> order
  dianggap terisi, kirim notifikasi konfirmasi singkat.
- Kalau belum -> signal dianggap batal/skip, user tidak perlu entry lagi.
"""

import logging
from datetime import datetime

from twelvedata_client import fetch_candles, TwelveDataError
from telegram_sender import send_message
from config import TF_ENTRY, PENDING_ORDER_TIMEOUT_MINUTES

logger = logging.getLogger(__name__)


def _price_touched_since(entry_price: float, since: datetime) -> bool:
    """Cek apakah candle M1 sejak `since` pernah mencakup entry_price di range low-high nya."""
    # outputsize dilebihkan sedikit dari timeout supaya aman kalau ada delay/misfire job
    candles = fetch_candles(interval=TF_ENTRY, outputsize=PENDING_ORDER_TIMEOUT_MINUTES + 15)
    relevant = [c for c in candles if c.time >= since]

    for c in relevant:
        if c.low <= entry_price <= c.high:
            return True
    return False


def check_pending_order(entry_price: float, order_type: str, signal_time: datetime) -> None:
    """
    Dipanggil oleh scheduler PENDING_ORDER_TIMEOUT_MINUTES setelah signal dikirim.
    Mengirim notifikasi konfirmasi (terisi) atau pembatalan (skip) ke Telegram.
    """
    logger.info("Cek status pending order %s @ %s (signal jam %s)",
                order_type, entry_price, signal_time.strftime("%H:%M"))
    try:
        filled = _price_touched_since(entry_price, signal_time)
    except TwelveDataError:
        logger.exception("Gagal cek status pending order — data Twelve Data error")
        return
    except Exception:
        logger.exception("Gagal cek status pending order")
        return

    if filled:
        logger.info("Pending order @ %s sudah tersentuh harga", entry_price)
        send_message(
            f"✅ *Update Order*\n"
            f"Pending {order_type} @ `{entry_price}` sudah tersentuh harga.\n"
            f"Posisi dianggap aktif — pantau SL/TP sesuai signal sebelumnya."
        )
    else:
        logger.info("Pending order @ %s belum tersentuh dalam %s menit, signal di-skip",
                     entry_price, PENDING_ORDER_TIMEOUT_MINUTES)
        send_message(
            f"⏭️ *Signal Skip*\n"
            f"Pending {order_type} @ `{entry_price}` belum tersentuh dalam "
            f"{PENDING_ORDER_TIMEOUT_MINUTES} menit.\n"
            f"Signal ini *dibatalkan* — tidak perlu entry lagi, tunggu signal H1 berikutnya."
        )
