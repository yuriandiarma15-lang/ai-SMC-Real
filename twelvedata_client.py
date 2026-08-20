"""
Wrapper sederhana untuk endpoint Twelve Data time_series.

Dokumentasi:
https://twelvedata.com/docs#time-series

Free plan Twelve Data:
800 credit/hari, 8 credit/menit.

Bot ini membutuhkan sekitar:
- 1 credit untuk M5
- 1 credit untuk M1
per signal.

Ditambahkan retry + backoff untuk menghadapi rate limit.

Perbaikan penting:
- Semua Candle.time dibuat timezone-aware.
- Jika Twelve Data mengembalikan datetime tanpa timezone,
  otomatis dianggap berada pada TIMEZONE dari config.py.
- Jika Twelve Data mengembalikan datetime dengan timezone,
  otomatis dikonversi ke TIMEZONE dari config.py.
"""

import logging
import time
import requests

from dataclasses import dataclass
from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

from config import (
    TWELVEDATA_API_KEY,
    SYMBOL,
    TIMEZONE,
)


# =========================================================
# LOGGING
# =========================================================

logger = logging.getLogger(__name__)


# =========================================================
# TWELVE DATA API
# =========================================================

BASE_URL = (
    "https://api.twelvedata.com/time_series"
)

USAGE_URL = (
    "https://api.twelvedata.com/api_usage"
)


# =========================================================
# RETRY CONFIG
# =========================================================

MAX_RETRIES = 3

RETRY_BACKOFF_SECONDS = 20


# =========================================================
# TIMEZONE
# =========================================================

try:

    DATA_TIMEZONE = ZoneInfo(
        TIMEZONE
    )

except Exception:

    logger.exception(
        "TIMEZONE tidak valid: %s",
        TIMEZONE,
    )

    raise


# =========================================================
# CANDLE
# =========================================================

@dataclass
class Candle:

    time: datetime

    open: float

    high: float

    low: float

    close: float

    @property
    def is_bullish(self) -> bool:

        return (
            self.close
            > self.open
        )

    @property
    def is_bearish(self) -> bool:

        return (
            self.close
            < self.open
        )

    @property
    def body(self) -> float:

        return abs(
            self.close
            - self.open
        )

    @property
    def range(self) -> float:

        return (
            self.high
            - self.low
        )


# =========================================================
# ERROR
# =========================================================

class TwelveDataError(Exception):

    pass


# =========================================================
# DATETIME PARSER
# =========================================================

def _parse_candle_datetime(
    value: str,
) -> datetime:
    """
    Parse datetime dari Twelve Data dan memastikan hasilnya
    selalu timezone-aware.

    Kasus 1:
        Twelve Data mengembalikan datetime tanpa timezone.

        Contoh:
            2026-08-21 04:10:00

        Maka datetime dianggap berada pada TIMEZONE config.

    Kasus 2:
        Twelve Data mengembalikan datetime dengan timezone.

        Maka datetime dikonversi ke TIMEZONE config.

    Return:
        datetime timezone-aware.
    """

    if not value:

        raise TwelveDataError(
            "Datetime candle kosong dari Twelve Data."
        )

    try:

        candle_time = (
            datetime.fromisoformat(
                value
            )
        )

    except ValueError as exc:

        raise TwelveDataError(
            f"Format datetime candle tidak valid: {value}"
        ) from exc

    # -----------------------------------------------------
    # NAIVE DATETIME
    # -----------------------------------------------------

    if candle_time.tzinfo is None:

        candle_time = (
            candle_time.replace(
                tzinfo=DATA_TIMEZONE
            )
        )

    # -----------------------------------------------------
    # AWARE DATETIME
    # -----------------------------------------------------

    else:

        candle_time = (
            candle_time.astimezone(
                DATA_TIMEZONE
            )
        )

    return candle_time


# =========================================================
# FETCH CANDLES
# =========================================================

def fetch_candles(
    interval: str,
    outputsize: int,
) -> List[Candle]:
    """
    Ambil candle terakhir untuk SYMBOL.

    Parameter:

        interval:
            Contoh:
                "1min"
                "5min"

        outputsize:
            Jumlah candle yang diminta.

    Return:

        List[Candle]

    Candle dikembalikan terurut:

        LAMA -> BARU

    sehingga:

        candles[-1]

    adalah candle paling baru.

    Semua Candle.time dijamin timezone-aware
    menggunakan TIMEZONE dari config.py.
    """

    if outputsize <= 0:

        raise ValueError(
            "outputsize harus lebih besar dari 0."
        )

    params = {

        "symbol": SYMBOL,

        "interval": interval,

        "outputsize": outputsize,

        "apikey": TWELVEDATA_API_KEY,

        "timezone": TIMEZONE,

        "order": "ASC",
    }

    data = None

    # =====================================================
    # REQUEST + RETRY
    # =====================================================

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):

        try:

            response = requests.get(

                BASE_URL,

                params=params,

                timeout=15,
            )

            credits_left = (
                response.headers.get(
                    "api-credits-left"
                )
            )

            if credits_left is not None:

                logger.info(
                    "Twelve Data credit tersisa: %s",
                    credits_left,
                )

                if (
                    credits_left.isdigit()
                    and int(credits_left) < 50
                ):

                    logger.warning(
                        "Sisa credit Twelve Data "
                        "tinggal %s — mendekati "
                        "limit harian!",
                        credits_left,
                    )

            # -------------------------------------------------
            # JSON
            # -------------------------------------------------

            data = response.json()

            # -------------------------------------------------
            # RATE LIMIT
            # -------------------------------------------------

            is_rate_limited = (

                response.status_code == 429

                or

                data.get("code") == 429
            )

            if is_rate_limited:

                logger.warning(

                    "Kena rate limit Twelve Data "
                    "(percobaan %s/%s), "
                    "tunggu %ss...",

                    attempt,

                    MAX_RETRIES,

                    RETRY_BACKOFF_SECONDS,
                )

                if attempt < MAX_RETRIES:

                    time.sleep(
                        RETRY_BACKOFF_SECONDS
                    )

                    continue

            break

        except requests.RequestException:

            logger.exception(

                "Request Twelve Data gagal "
                "(percobaan %s/%s)",

                attempt,

                MAX_RETRIES,
            )

            if attempt < MAX_RETRIES:

                time.sleep(
                    RETRY_BACKOFF_SECONDS
                )

                continue

            raise TwelveDataError(
                "Gagal menghubungi Twelve Data "
                "setelah beberapa percobaan."
            )

        except ValueError:

            logger.exception(
                "Response Twelve Data "
                "bukan JSON yang valid."
            )

            raise TwelveDataError(
                "Response Twelve Data tidak valid."
            )

    # =====================================================
    # VALIDASI RESPONSE
    # =====================================================

    if not data:

        raise TwelveDataError(
            "Tidak ada response dari Twelve Data."
        )

    if (
        data.get("status") == "error"
        or "values" not in data
    ):

        msg = data.get(
            "message",
            "Unknown error dari Twelve Data",
        )

        logger.error(
            "Twelve Data error: %s",
            msg,
        )

        raise TwelveDataError(
            msg
        )

    values = data.get(
        "values",
        [],
    )

    if not values:

        raise TwelveDataError(
            "Twelve Data tidak mengembalikan candle."
        )

    # =====================================================
    # PARSE CANDLES
    # =====================================================

    candles = []

    for row in values:

        try:

            candle_time = (
                _parse_candle_datetime(
                    row["datetime"]
                )
            )

            candle = Candle(

                time=candle_time,

                open=float(
                    row["open"]
                ),

                high=float(
                    row["high"]
                ),

                low=float(
                    row["low"]
                ),

                close=float(
                    row["close"]
                ),
            )

            candles.append(
                candle
            )

        except KeyError as exc:

            logger.exception(
                "Data candle Twelve Data "
                "tidak lengkap: %s",
                row,
            )

            raise TwelveDataError(
                f"Field candle tidak lengkap: {exc}"
            ) from exc

        except (TypeError, ValueError) as exc:

            logger.exception(
                "Data candle Twelve Data "
                "tidak valid: %s",
                row,
            )

            raise TwelveDataError(
                f"Data candle tidak valid: {row}"
            ) from exc

    if not candles:

        raise TwelveDataError(
            "Tidak ada candle valid "
            "setelah parsing."
        )

    # =====================================================
    # SORT
    # =====================================================

    candles.sort(
        key=lambda c: c.time
    )

    # =====================================================
    # LOG
    # =====================================================

    logger.debug(

        "Berhasil mengambil %s candle %s "
        "untuk %s",

        len(candles),

        interval,

        SYMBOL,
    )

    return candles


# =========================================================
# CHECK REMAINING QUOTA
# =========================================================

def check_remaining_quota() -> dict:
    """
    Cek sisa credit Twelve Data.

    Catatan:
    Endpoint /api_usage dapat menggunakan credit,
    jadi jangan dipanggil pada setiap signal.

    Gunakan hanya untuk pengecekan manual.
    """

    try:

        response = requests.get(

            USAGE_URL,

            params={
                "apikey":
                    TWELVEDATA_API_KEY
            },

            timeout=15,
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException as exc:

        logger.exception(
            "Gagal mengecek quota Twelve Data."
        )

        raise TwelveDataError(
            "Gagal mengecek quota Twelve Data."
        ) from exc


# =========================================================
# CURRENT PRICE
# =========================================================

def get_current_price() -> float:
    """
    Ambil harga close candle M1 paling baru.

    Digunakan sebagai referensi harga saat ini.
    """

    candles = fetch_candles(

        interval="1min",

        outputsize=1,
    )

    if not candles:

        raise TwelveDataError(
            "Tidak ada data harga terkini."
        )

    return candles[-1].close
