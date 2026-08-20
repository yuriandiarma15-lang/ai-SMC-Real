"""
Wrapper sederhana untuk endpoint Twelve Data time_series.
Dokumentasi: https://twelvedata.com/docs#time-series

Free plan Twelve Data: 800 credit/hari, 8 credit/menit, 1x time_series = 1 credit.
Bot ini butuh ~2 credit per signal (M5 + M1) x ~20 signal/hari = ~40 credit/hari,
jauh di bawah limit. Tapi tetap ditambahkan retry+backoff untuk jaga-jaga kalau
kena limit per-menit (misalnya waktu testing manual berkali-kali beruntun).
"""

import logging
import time
import requests
from dataclasses import dataclass
from datetime import datetime
from typing import List

from config import TWELVEDATA_API_KEY, SYMBOL, TIMEZONE

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com/time_series"
USAGE_URL = "https://api.twelvedata.com/api_usage"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 20  # limit per-menit reset tiap 60 detik, 20 detik cukup aman


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low


class TwelveDataError(Exception):
    pass


def fetch_candles(interval: str, outputsize: int) -> List[Candle]:
    """
    Ambil candle terakhir untuk SYMBOL pada interval tertentu.
    Return list candle terurut dari LAMA -> BARU (index terakhir = candle paling baru).
    """
    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY,
        "timezone": TIMEZONE,
        "order": "ASC",
    }

    data = None
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(BASE_URL, params=params, timeout=15)

        credits_left = resp.headers.get("api-credits-left")
        if credits_left is not None:
            logger.info("Twelve Data credit tersisa: %s", credits_left)
            if credits_left.isdigit() and int(credits_left) < 50:
                logger.warning("Sisa credit Twelve Data tinggal %s — mendekati limit harian!", credits_left)

        data = resp.json()

        is_rate_limited = resp.status_code == 429 or data.get("code") == 429
        if is_rate_limited:
            logger.warning(
                "Kena rate limit Twelve Data (percobaan %s/%s), tunggu %ss...",
                attempt, MAX_RETRIES, RETRY_BACKOFF_SECONDS,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue

        break

    if data.get("status") == "error" or "values" not in data:
        msg = data.get("message", "Unknown error dari Twelve Data")
        logger.error("Twelve Data error: %s", msg)
        raise TwelveDataError(msg)

    candles = []
    for row in data["values"]:
        candles.append(
            Candle(
                time=datetime.fromisoformat(row["datetime"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
        )
    # Twelve Data dengan order=ASC harusnya sudah lama->baru, tapi kita pastikan lagi
    candles.sort(key=lambda c: c.time)
    return candles


def check_remaining_quota() -> dict:
    """
    Cek sisa credit hari ini via endpoint /api_usage.
    NOTE: memanggil endpoint ini sendiri memakan 1 credit, jadi jangan dipanggil
    tiap job — cukup dipakai manual sesekali kalau mau cek ('python -c ...').
    """
    resp = requests.get(USAGE_URL, params={"apikey": TWELVEDATA_API_KEY}, timeout=15)
    return resp.json()


def get_current_price() -> float:
    """Harga close candle M1 paling baru, dipakai sebagai referensi harga live."""
    candles = fetch_candles(interval="1min", outputsize=1)
    if not candles:
        raise TwelveDataError("Tidak ada data harga terkini")
    return candles[-1].close
