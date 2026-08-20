"""
Menggabungkan:
- Analisa struktur SMC di M5
- Timing entry presisi di M1
- Risk management
- Format signal Telegram

Mode:
- generate_signal()
    -> dipakai scheduler otomatis
    -> menggunakan CANDLES_LOOKBACK sesuai config

- generate_signal(structure_candle_count=12)
    -> dipakai /signal manual
    -> menggunakan 12 candle M5 CLOSED terakhir

PERUBAHAN PENTING (fix entry logic):
- OB / FVG yang BELUM pernah disentuh harga (M1 terakhir) -> tetap PENDING ORDER
  di harga zona tersebut (sesuai filosofi SMC: tunggu retest).
- OB / FVG yang SUDAH disentuh/retest oleh harga -> entry MARKET LANGSUNG
  di harga sekarang, karena zona sudah "dikonfirmasi" -> tidak perlu pending
  order lagi ke harga yang sudah dilewati.
- Ditambahkan MAX_ZONE_DISTANCE supaya zona yang kejauhan dari harga sekarang
  (biasanya saat trend kuat) tidak dipaksa jadi pending order yang jarang
  kesentuh -> fallback ke market entry.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from twelvedata_client import Candle, fetch_candles
from smc_analyzer import analyze, SMCResult
from entry_reason_bank import get_entry_reason, get_session_extra_note

from config import (
    CANDLES_FOR_STRUCTURE,
    CANDLES_LOOKBACK,
    CANDLES_ENTRY_LOOKBACK,
    TF_STRUCTURE,
    TF_ENTRY,
    SL_DISTANCE,
    TP1_DISTANCE,
    TP2_DISTANCE,
    SL_PIPS,
    TP1_PIPS,
    TP2_PIPS,
    SESSIONS,
    MARKET_ENTRY_TOLERANCE,
    PENDING_ORDER_TIMEOUT_MINUTES,
    TIMEZONE,
)

# Jarak maksimal (dalam satuan harga, sama seperti SL_DISTANCE dst.)
# antara harga sekarang dengan zona OB/FVG supaya zona itu masih layak
# dipakai sebagai pending order. Kalau lebih jauh dari ini -> market entry.
# Sesuaikan nilainya di config.py kalau perlu (kasih default di sini
# supaya tetap jalan walau belum ditambahkan ke config).
try:
    from config import MAX_ZONE_DISTANCE
except ImportError:
    MAX_ZONE_DISTANCE = SL_DISTANCE * 1.5  # default: 1.5x jarak SL


# =========================================================
# TIMEZONE
# =========================================================

WIB = ZoneInfo(TIMEZONE)


# =========================================================
# TRADE SIGNAL
# =========================================================

@dataclass
class TradeSignal:
    timestamp: datetime
    bias: str
    entry_price: float
    entry_type: str
    order_type: str
    is_pending: bool
    sl: float
    tp1: float
    tp2: float
    probability: int
    reasons: List[str]
    smc: SMCResult
    session_name: str
    session_note: str
    zone_touched: bool = False
    zone_type: Optional[str] = None


# =========================================================
# SESSION
# =========================================================

def _get_session_info(dt: datetime) -> tuple[str, str]:
    """
    Tentukan sesi trading berdasarkan jam WIB.
    """

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=WIB)
    else:
        dt = dt.astimezone(WIB)

    hour = dt.hour

    for session in SESSIONS:
        if hour in session["hours"]:
            return (
                session["name"],
                session["note"],
            )

    return (
        "Trading",
        "pantau pergerakan harga dengan disiplin & manajemen risiko",
    )


# =========================================================
# CANDLE TIME HELPERS
# =========================================================

def _to_wib(dt: datetime) -> datetime:
    """
    Pastikan datetime candle berada dalam timezone WIB.

    Twelve Data dapat mengembalikan datetime timezone-naive
    tergantung parameter/API response.
    """

    if dt.tzinfo is None:
        return dt.replace(tzinfo=WIB)

    return dt.astimezone(WIB)


def _get_current_m5_open_time(now: datetime) -> datetime:
    """
    Tentukan awal candle M5 yang sedang berjalan.
    """

    now = now.astimezone(WIB)
    minute = (now.minute // 5) * 5

    return now.replace(
        minute=minute,
        second=0,
        microsecond=0,
    )


def _get_closed_m5_candles(
    candles: List[Candle],
    count: int,
) -> List[Candle]:
    """
    Ambil `count` candle M5 yang benar-benar sudah CLOSED.
    """

    if count <= 0:
        raise ValueError(
            "Jumlah candle closed harus lebih besar dari 0."
        )

    now = datetime.now(WIB)
    current_m5_open = _get_current_m5_open_time(now)

    closed = []

    for candle in candles:
        candle_time = _to_wib(candle.time)

        if candle_time < current_m5_open:
            closed.append(candle)

    closed.sort(key=lambda c: _to_wib(c.time))

    if len(closed) < count:
        raise ValueError(
            "Candle M5 closed tidak cukup. "
            f"Tersedia {len(closed)}, "
            f"dibutuhkan {count}. "
            f"Waktu sekarang WIB: "
            f"{now.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    return closed[-count:]


# =========================================================
# ZONE TOUCH CHECK
# =========================================================

def _zone_touched_by_recent_price(
    zone_low: float,
    zone_high: float,
    recent_candles: List[Candle],
) -> bool:
    """
    Cek apakah range candle M1 terakhir sudah overlap dengan
    range zona (OB/FVG). Kalau overlap -> zona dianggap sudah
    "kejemput" / diretest oleh harga.
    """

    if not recent_candles:
        return False

    recent_low = min(c.low for c in recent_candles)
    recent_high = max(c.high for c in recent_candles)

    # Overlap check: dua range TIDAK overlap kalau salah satu
    # sepenuhnya di atas atau di bawah yang lain.
    no_overlap = (
        zone_high < recent_low
        or zone_low > recent_high
    )

    return not no_overlap


# =========================================================
# ORDER TYPE
# =========================================================

def _determine_order_type(
    bias: str,
    entry_price: float,
    current_price: float,
    has_zone: bool,
    zone_touched: bool = False,
) -> tuple[str, bool]:

    # Zona sudah kejemput / tidak ada zona valid -> selalu market.
    if (
        not has_zone
        or zone_touched
        or abs(entry_price - current_price) <= MARKET_ENTRY_TOLERANCE
    ):
        return "Market", False

    if bias == "bullish":
        if entry_price < current_price:
            return "Buy Limit", True
        return "Buy Stop", True

    else:
        if entry_price > current_price:
            return "Sell Limit", True
        return "Sell Stop", True


# =========================================================
# FIND ENTRY ZONE
# =========================================================

def _find_entry_zone(
    smc: SMCResult,
    current_price: float,
    recent_candles: List[Candle],
    max_distance: float = MAX_ZONE_DISTANCE,
):
    """
    Cari zona OB/FVG yang paling dekat dengan harga sekarang,
    dalam batas `max_distance`.

    Return: (price, zone_type, zone_touched)
        - price        : titik tengah zona (dipakai kalau belum kejemput)
        - zone_type    : "Order Block" / "Fair Value Gap"
        - zone_touched : True kalau zona ini sudah overlap dengan
                          range candle M1 terakhir (sudah diretest)
    """

    candidates = []

    for ob in smc.order_blocks:
        mid = (ob.high + ob.low) / 2
        dist = abs(current_price - mid)

        if max_distance and dist > max_distance:
            continue

        touched = _zone_touched_by_recent_price(
            ob.low, ob.high, recent_candles
        )

        candidates.append((dist, mid, "Order Block", touched))

    for fvg in smc.fvgs:
        mid = (fvg.top + fvg.bottom) / 2
        dist = abs(current_price - mid)

        if max_distance and dist > max_distance:
            continue

        touched = _zone_touched_by_recent_price(
            fvg.bottom, fvg.top, recent_candles
        )

        candidates.append((dist, mid, "Fair Value Gap", touched))

    if not candidates:
        return None, None, False

    # Prioritaskan zona yang BELUM kejemput dan terdekat.
    # Kalau semua zona dalam radius sudah kejemput, ambil yang
    # terdekat saja (nanti tetap jadi market entry).
    untouched = [c for c in candidates if not c[3]]

    pool = untouched if untouched else candidates
    pool.sort(key=lambda x: x[0])

    _, price, zone_type, touched = pool[0]

    return price, zone_type, touched


# =========================================================
# ENTRY DESCRIPTION
# =========================================================

def _build_entry_description(
    order_type: str,
    is_pending: bool,
    zone_touched: bool,
) -> str:

    if not is_pending:
        if zone_touched:
            return (
                "Market "
                "(zona OB/FVG sudah kejemput/diretest, entry langsung)"
            )
        return (
            "Market "
            "(harga sudah di zona optimal / tidak ada zona valid)"
        )

    return (
        f"Pending {order_type} "
        "(pasang order, tunggu harga menuju zona OB/FVG)"
    )


# =========================================================
# GENERATE SIGNAL
# =========================================================

def generate_signal(
    structure_candle_count: Optional[int] = None,
) -> TradeSignal:

    now = datetime.now(WIB)

    if structure_candle_count is None:
        m5_outputsize = CANDLES_LOOKBACK
    else:
        m5_outputsize = max(structure_candle_count + 8, 20)

    structure_raw = fetch_candles(
        interval=TF_STRUCTURE,
        outputsize=m5_outputsize,
    )

    if not structure_raw:
        raise ValueError("Twelve Data tidak mengembalikan candle M5.")

    if structure_candle_count is not None:
        structure_candles = _get_closed_m5_candles(
            structure_raw, structure_candle_count
        )

        first_time = _to_wib(structure_candles[0].time)
        last_time = _to_wib(structure_candles[-1].time)

        print(
            "[M5 CLOSED] "
            f"{len(structure_candles)} candle | "
            f"{first_time.strftime('%H:%M')} -> "
            f"{last_time.strftime('%H:%M')} WIB"
        )
    else:
        if len(structure_raw) < CANDLES_FOR_STRUCTURE:
            raise ValueError(
                "Data candle M5 tidak cukup. "
                f"Tersedia {len(structure_raw)}, "
                f"dibutuhkan {CANDLES_FOR_STRUCTURE}."
            )
        structure_candles = structure_raw

    smc = analyze(structure_candles)

    entry_candles = fetch_candles(
        interval=TF_ENTRY,
        outputsize=CANDLES_ENTRY_LOOKBACK,
    )

    if not entry_candles:
        raise ValueError("Data candle M1 tidak tersedia.")

    current_price = entry_candles[-1].close

    recent_candles = (
        entry_candles[-10:]
        if len(entry_candles) >= 10
        else entry_candles
    )

    # =====================================================
    # FIND ENTRY ZONE (dengan status touched)
    # =====================================================

    zone_price, zone_type, zone_touched = _find_entry_zone(
        smc, current_price, recent_candles
    )

    has_zone = zone_price is not None

    # =====================================================
    # ENTRY PRICE
    #
    # - Belum ada zona valid            -> market di harga sekarang
    # - Zona sudah kejemput/diretest    -> market di harga sekarang
    # - Zona ada & belum kejemput       -> pending di harga zona
    # =====================================================

    if has_zone and not zone_touched:
        entry_price = zone_price
    else:
        entry_price = current_price

    order_type, is_pending = _determine_order_type(
        smc.bias,
        entry_price,
        current_price,
        has_zone,
        zone_touched,
    )

    entry_type = _build_entry_description(
        order_type, is_pending, zone_touched
    )

    # =====================================================
    # CONFLUENCE / ALASAN (pakai reason bank biar variatif)
    # =====================================================

    if zone_type:
        reason_text = get_entry_reason(
            bias=smc.bias,
            zone_type=zone_type,
            is_pending=is_pending,
            touched=zone_touched,
            seed=f"{now.isoformat()}-{zone_type}-{smc.bias}",
        )
        smc.confluences.append(reason_text)

    if is_pending:
        smc.confluences.append(
            f"Harga sekarang ({round(current_price, 2)}) "
            f"masih berjarak dari zona optimal — "
            f"gunakan pending order, bukan market"
        )

    # =====================================================
    # SL / TP
    # =====================================================

    if smc.bias == "bullish":
        sl = entry_price - SL_DISTANCE
        tp1 = entry_price + TP1_DISTANCE
        tp2 = entry_price + TP2_DISTANCE
    else:
        sl = entry_price + SL_DISTANCE
        tp1 = entry_price - TP1_DISTANCE
        tp2 = entry_price - TP2_DISTANCE

    now = datetime.now(WIB)
    session_name, session_note = _get_session_info(now)

    # Tambahkan variasi catatan sesi (opsional, biar tidak monoton
    # tiap kali sinyal keluar di sesi yang sama)
    extra_note = get_session_extra_note(
        session_name=session_name,
        seed=f"{now.isoformat()}-{session_name}",
    )
    if extra_note:
        session_note = f"{session_note}. {extra_note}"

    return TradeSignal(
        timestamp=now,
        bias=smc.bias,
        entry_price=round(entry_price, 2),
        entry_type=entry_type,
        order_type=order_type,
        is_pending=is_pending,
        sl=round(sl, 2),
        tp1=round(tp1, 2),
        tp2=round(tp2, 2),
        probability=smc.score,
        reasons=smc.confluences,
        smc=smc,
        session_name=session_name,
        session_note=session_note,
        zone_touched=zone_touched,
        zone_type=zone_type,
    )


# =========================================================
# FORMAT SIGNAL
# =========================================================

def format_signal_message(sig: TradeSignal) -> str:

    arrow = "🟢 BUY" if sig.bias == "bullish" else "🔴 SELL"
    time_str = sig.timestamp.strftime("%d %b %Y, %H:%M WIB")
    entry_label = f"🎯 Entry ({sig.order_type})"

    lines = [
        "📊 *XAU AI INTELLIGENCE*",
        f"_Signal H1 — {time_str}_",
        f"_Sesi {sig.session_name}_",
        "",
        f"{arrow}  XAUUSD",
        f"Tipe entry : {sig.entry_type}",
        "",
        f"{entry_label} : `{int(sig.entry_price)}`",
        f"🛑 SL     : `{int(sig.sl)}`  (-{SL_PIPS} pip)",
        f"✅ TP1    : `{int(sig.tp1)}`  (+{TP1_PIPS} pip)",
        f"✅ TP2    : `{int(sig.tp2)}`  (+{TP2_PIPS} pip)",
        "",
        f"📈 Probabilitas: *{sig.probability}%*",
        "",
        f"🕐 Catatan sesi {sig.session_name}:",
        _wrap_reason(sig.session_note),
        "",
        "🧠 Alasan entry:",
    ]

    for i, reason in enumerate(sig.reasons, 1):
        lines.append(_wrap_reason(f"{i}. {reason}"))

    if sig.is_pending:
        lines += [
            "",
            _wrap_reason(
                f"⏳ Pasang {sig.order_type} di harga entry di atas. "
                f"Kalau dalam {PENDING_ORDER_TIMEOUT_MINUTES} menit "
                f"belum kesentuh, signal ini otomatis dianggap batal "
                f"(skip, tidak perlu entry lagi)."
            ),
        ]

    lines += [
        "",
        "⚠️ _Signal berbasis AI (SMC), bukan jaminan profit._",
        "_Selalu gunakan money management pribadi._",
        "",
        "🤖 _Signal ini dihasilkan oleh AI Agent Gold_",
    ]

    return "\n".join(lines)


# =========================================================
# WRAP TEXT
# =========================================================

def _wrap_reason(text: str, width: int = 34) -> str:

    words = text.split(" ")
    lines = []
    current = ""

    for word in words:
        if len(current) + len(word) + 1 > width:
            if current:
                lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()

    if current:
        lines.append(current)

    return "\n   ".join(lines)
