"""
Konfigurasi global untuk XAU AI Signal Bot.
Semua nilai sensitif diambil dari environment variable (.env),
JANGAN hardcode API key / token di sini.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# === CREDENTIALS ===
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # chat ID pribadi admin, bot kirim langsung ke sini (bukan grup/channel)
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")

# === PASANGAN & TIMEFRAME ===
SYMBOL = "XAU/USD"
TF_STRUCTURE = "5min"   # timeframe untuk analisa SMC struktur (12 candle = 1 jam)
TF_ENTRY = "1min"       # timeframe untuk saran entry presisi
CANDLES_FOR_STRUCTURE = 12   # 12 x M5 = H1
CANDLES_LOOKBACK = 60        # ambil lebih banyak candle biar swing high/low & OB akurat
CANDLES_ENTRY_LOOKBACK = 30  # candle M1 yang dicek untuk entry

# === RISK MANAGEMENT ===
# 1 pip XAUUSD diasumsikan = 0.1 (konvensi broker ID: HFM, Exness, VALETAX, FXGT)
# Kalau broker kamu pakai 1 pip = 1.0 (harga 4 digit tanpa desimal pip),
# tinggal ubah PIP_VALUE ini, seluruh logic lain otomatis menyesuaikan.
PIP_VALUE = 0.1

SL_PIPS = 50
TP1_PIPS = 70
TP2_PIPS = 150

SL_DISTANCE = SL_PIPS * PIP_VALUE     # = 5.0 USD
TP1_DISTANCE = TP1_PIPS * PIP_VALUE   # = 7.0 USD
TP2_DISTANCE = TP2_PIPS * PIP_VALUE   # = 15.0 USD

# Kalau OB/FVG jaraknya dari harga sekarang masih di bawah threshold ini (dalam USD),
# entry dianggap "sudah dekat" dan boleh market. Di atas threshold ini -> wajib pending order.
# 0.3 USD = 3 pip (dengan PIP_VALUE=0.1)
MARKET_ENTRY_TOLERANCE = 0.3

# Kalau pending order belum kesentuh harga dalam sekian menit, signal dianggap batal/skip.
PENDING_ORDER_TIMEOUT_MINUTES = 20

# === JADWAL SIGNAL (WIB / Asia/Jakarta) ===
TIMEZONE = "Asia/Jakarta"

# Jam-jam aktif dalam satu "hari sesi": 07:00 - 23:00 lalu lanjut 00:00 - 02:00 keesokan harinya.
ACTIVE_HOURS_MAIN = list(range(7, 24))   # 07:00 s.d 23:00
ACTIVE_HOURS_EXTENDED = [0, 1, 2]        # 00:00, 01:00, 02:00 (dini hari lanjutan sesi sebelumnya)

# Pasar XAUUSD tutup Sabtu-Minggu. Sesi terakhir minggu ini adalah Jumat malam,
# yang nyambung sampai Sabtu dini hari 02:00 WIB (baru itu pasar benar-benar tutup).
# Jadi:
# - Jam utama (07-23)  -> aktif Senin-Jumat saja (Sabtu & Minggu TIDAK ada sesi 07-23)
# - Jam extended (00-02) -> kelanjutan sesi malam Senin-Jumat, jatuh di Selasa-Sabtu dini hari
#   (contoh: sesi Jumat 07:00-23:00 lanjut ke Sabtu dini hari 00:00-02:00, lalu bot LIBUR
#   total sampai Senin jam 07:00 lagi — tidak ada sesi Sabtu siang & Minggu sama sekali)
DOW_MAIN = "mon,tue,wed,thu,fri"        # cron day_of_week untuk jam 07-23
DOW_EXTENDED = "tue,wed,thu,fri,sat"    # cron day_of_week untuk jam 00-02

# === MISC ===
MAX_MESSAGE_WIDTH = 34  # target lebar baris teks Telegram (karakter) biar tidak wrap aneh di HP
LOG_LEVEL = "INFO"

# === SESI TRADING (WIB) ===
# Dipakai untuk kasih konteks karakter market di tiap signal.
# Batas jam disederhanakan ke jam bulat biar gampang dipetakan ke jam kirim signal.
SESSIONS = [
    {
        "name": "Asia",
        "hours": list(range(7, 15)),  # 07:00 - 14:59 WIB
        "note": "pergerakan cenderung tenang & choppy, cocok entry dengan "
                "konfirmasi ketat, hindari overtrading di range sempit",
    },
    {
        "name": "London",
        "hours": list(range(15, 20)),  # 15:00 - 19:59 WIB
        "note": "volatilitas mulai naik, sering jadi awal breakout struktur "
                "harga XAUUSD, waktu favorit smart money mulai bergerak",
    },
    {
        "name": "New York",
        # 20:00 - 23:59 lanjut 00:00 - 02:00 dini hari (overlap London-NY & sesi NY murni)
        "hours": list(range(20, 24)) + [0, 1, 2],
        "note": "sesi paling likuid & volatil, rawan spike menembus level SMC, "
                "tetap waspada berita fundamental (NFP/CPI/FOMC)",
    },
]
