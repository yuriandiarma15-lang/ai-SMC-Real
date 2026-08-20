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
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from twelvedata_client import Candle, fetch_candles
from smc_analyzer import analyze, SMCResult

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

    Contoh:
        11:37 -> 11:35
        11:34 -> 11:30
        11:30 -> 11:30
        11:00 -> 11:00
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

    Candle yang open time-nya sama dengan candle M5 saat ini
    tidak digunakan.

    Contoh saat 11:37:

        11:35 -> candle berjalan -> BUANG
        11:30 -> closed
        11:25 -> closed
        ...
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

        # Candle hanya dianggap closed kalau
        # waktu OPEN candle lebih kecil dari
        # open time candle M5 yang sedang berjalan.
        if candle_time < current_m5_open:
            closed.append(candle)

    # Pastikan urutan lama -> baru.
    closed.sort(
        key=lambda c: _to_wib(c.time)
    )

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
# ORDER TYPE
# =========================================================

def _determine_order_type(
    bias: str,
    entry_price: float,
    current_price: float,
    has_zone: bool,
) -> tuple[str, bool]:

    if (
        not has_zone
        or abs(entry_price - current_price)
        <= MARKET_ENTRY_TOLERANCE
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
):
    """
    Cari zona OB/FVG yang paling dekat
    dengan harga sekarang.
    """

    candidates = []

    # -----------------------------------------------------
    # ORDER BLOCK
    # -----------------------------------------------------

    for ob in smc.order_blocks:

        mid = (
            ob.high + ob.low
        ) / 2

        candidates.append(
            (
                abs(current_price - mid),
                mid,
                "Order Block",
            )
        )

    # -----------------------------------------------------
    # FAIR VALUE GAP
    # -----------------------------------------------------

    for fvg in smc.fvgs:

        mid = (
            fvg.top + fvg.bottom
        ) / 2

        candidates.append(
            (
                abs(current_price - mid),
                mid,
                "Fair Value Gap",
            )
        )

    if not candidates:
        return None, None

    candidates.sort(
        key=lambda x: x[0]
    )

    _, price, zone_type = candidates[0]

    return price, zone_type


# =========================================================
# ENTRY DESCRIPTION
# =========================================================

def _build_entry_description(
    order_type: str,
    is_pending: bool,
    m1_candles: List[Candle],
    entry_price: float,
) -> str:

    if not is_pending:

        return (
            "Market "
            "(harga sudah di zona optimal)"
        )

    recent_candles = (
        m1_candles[-10:]
        if len(m1_candles) >= 10
        else m1_candles
    )

    if not recent_candles:

        return (
            f"Pending {order_type} "
            "(pasang order, tunggu harga menuju zona OB/FVG)"
        )

    recent_low = min(
        c.low for c in recent_candles
    )

    recent_high = max(
        c.high for c in recent_candles
    )

    already_touched = (
        recent_low
        <= entry_price
        <= recent_high
    )

    if already_touched:

        return (
            f"Pending {order_type} "
            "(zona OB/FVG barusan sempat tersentuh)"
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

    """
    Generate signal.

    structure_candle_count = None
        Scheduler normal.
        Menggunakan CANDLES_LOOKBACK.

    structure_candle_count = 12
        Digunakan oleh /signal.
        Menggunakan tepat 12 candle M5 CLOSED terakhir.
    """

    # =====================================================
    # CURRENT TIME WIB
    # =====================================================

    now = datetime.now(WIB)

    # =====================================================
    # M5 STRUCTURE
    # =====================================================

    if structure_candle_count is None:

        # Scheduler menggunakan lookback normal.
        m5_outputsize = CANDLES_LOOKBACK

    else:

        # Manual /signal.
        #
        # Ambil cukup banyak history supaya kalau candle
        # terakhir sedang berjalan, kita tetap punya
        # minimal 12 candle closed.
        #
        # 20 candle jauh lebih aman daripada hanya 13.
        m5_outputsize = max(
            structure_candle_count + 8,
            20,
        )

    structure_raw = fetch_candles(
        interval=TF_STRUCTURE,
        outputsize=m5_outputsize,
    )

    # =====================================================
    # CHECK DATA
    # =====================================================

    if not structure_raw:

        raise ValueError(
            "Twelve Data tidak mengembalikan candle M5."
        )

    # =====================================================
    # MANUAL /SIGNAL
    #
    # AMBIL 12 CANDLE M5 CLOSED
    # =====================================================

    if structure_candle_count is not None:

        structure_candles = _get_closed_m5_candles(
            structure_raw,
            structure_candle_count,
        )

        # Logging sederhana untuk memastikan candle
        # yang digunakan memang benar.
        first_time = _to_wib(
            structure_candles[0].time
        )

        last_time = _to_wib(
            structure_candles[-1].time
        )

        print(
            "[M5 CLOSED] "
            f"{len(structure_candles)} candle | "
            f"{first_time.strftime('%H:%M')} -> "
            f"{last_time.strftime('%H:%M')} WIB"
        )

    else:

        # Scheduler tetap menggunakan data sesuai config.
        if len(structure_raw) < CANDLES_FOR_STRUCTURE:

            raise ValueError(
                "Data candle M5 tidak cukup. "
                f"Tersedia {len(structure_raw)}, "
                f"dibutuhkan {CANDLES_FOR_STRUCTURE}."
            )

        structure_candles = structure_raw

    # =====================================================
    # SMC ANALYSIS
    # =====================================================

    smc = analyze(
        structure_candles
    )

    # =====================================================
    # M1 ENTRY
    # =====================================================

    entry_candles = fetch_candles(
        interval=TF_ENTRY,
        outputsize=CANDLES_ENTRY_LOOKBACK,
    )

    if not entry_candles:

        raise ValueError(
            "Data candle M1 tidak tersedia."
        )

    current_price = (
        entry_candles[-1].close
    )

    # =====================================================
    # FIND ENTRY ZONE
    # =====================================================

    zone_price, zone_type = (
        _find_entry_zone(
            smc,
            current_price,
        )
    )

    has_zone = (
        zone_price is not None
    )

    # =====================================================
    # ENTRY PRICE
    # =====================================================

    if has_zone:

        entry_price = zone_price

    else:

        entry_price = current_price

    # =====================================================
    # ORDER TYPE
    # =====================================================

    order_type, is_pending = (
        _determine_order_type(
            smc.bias,
            entry_price,
            current_price,
            has_zone,
        )
    )

    # =====================================================
    # ENTRY DESCRIPTION
    # =====================================================

    entry_type = (
        _build_entry_description(
            order_type,
            is_pending,
            entry_candles,
            entry_price,
        )
    )

    # =====================================================
    # CONFLUENCE
    # =====================================================

    if zone_type:

        smc.confluences.append(
            f"Entry mengacu ke {zone_type} "
            f"terdekat dari harga sekarang"
        )

    if is_pending:

        smc.confluences.append(
            f"Harga sekarang "
            f"({round(current_price, 2)}) "
            f"masih berjarak dari zona optimal — "
            f"gunakan pending order, bukan market"
        )

    # =====================================================
    # SL / TP
    # =====================================================

    if smc.bias == "bullish":

        sl = (
            entry_price
            - SL_DISTANCE
        )

        tp1 = (
            entry_price
            + TP1_DISTANCE
        )

        tp2 = (
            entry_price
            + TP2_DISTANCE
        )

    else:

        sl = (
            entry_price
            + SL_DISTANCE
        )

        tp1 = (
            entry_price
            - TP1_DISTANCE
        )

        tp2 = (
            entry_price
            - TP2_DISTANCE
        )

    # =====================================================
    # TIME / SESSION
    # =====================================================

    now = datetime.now(WIB)

    session_name, session_note = (
        _get_session_info(now)
    )

    # =====================================================
    # RESULT
    # =====================================================

    return TradeSignal(

        timestamp=now,

        bias=smc.bias,

        entry_price=round(
            entry_price,
            2,
        ),

        entry_type=entry_type,

        order_type=order_type,

        is_pending=is_pending,

        sl=round(
            sl,
            2,
        ),

        tp1=round(
            tp1,
            2,
        ),

        tp2=round(
            tp2,
            2,
        ),

        probability=smc.score,

        reasons=smc.confluences,

        smc=smc,

        session_name=session_name,

        session_note=session_note,
    )


# =========================================================
# FORMAT SIGNAL
# =========================================================

def format_signal_message(
    sig: TradeSignal,
) -> str:

    arrow = (
        "🟢 BUY"
        if sig.bias == "bullish"
        else "🔴 SELL"
    )

    time_str = (
        sig.timestamp.strftime(
            "%d %b %Y, %H:%M WIB"
        )
    )

    entry_label = (
        f"🎯 Entry ({sig.order_type})"
    )

    lines = [

        "📊 *XAU AI INTELLIGENCE*",

        f"_Signal H1 — {time_str}_",

        f"_Sesi {sig.session_name}_",

        "",

        f"{arrow}  XAUUSD",

        f"Tipe entry : {sig.entry_type}",

        "",

        f"{entry_label} : "
        f"`{sig.entry_price}`",

        f"🛑 SL     : "
        f"`{sig.sl}`  "
        f"(-{SL_PIPS} pip)",

        f"✅ TP1    : "
        f"`{sig.tp1}`  "
        f"(+{TP1_PIPS} pip)",

        f"✅ TP2    : "
        f"`{sig.tp2}`  "
        f"(+{TP2_PIPS} pip)",

        "",

        f"📈 Probabilitas: "
        f"*{sig.probability}%*",

        "",

        f"🕐 Catatan sesi "
        f"{sig.session_name}:",

        _wrap_reason(
            sig.session_note
        ),

        "",

        "🧠 Alasan entry:",
    ]

    # =====================================================
    # REASONS
    # =====================================================

    for i, reason in enumerate(
        sig.reasons,
        1,
    ):

        lines.append(
            _wrap_reason(
                f"{i}. {reason}"
            )
        )

    # =====================================================
    # PENDING
    # =====================================================

    if sig.is_pending:

        lines += [

            "",

            _wrap_reason(
                f"⏳ Pasang "
                f"{sig.order_type} "
                f"di harga entry di atas. "
                f"Kalau dalam "
                f"{PENDING_ORDER_TIMEOUT_MINUTES} "
                f"menit belum kesentuh, "
                f"signal ini otomatis "
                f"dianggap batal "
                f"(skip, tidak perlu entry lagi)."
            ),
        ]

    # =====================================================
    # FOOTER
    # =====================================================

    lines += [

        "",

        "⚠️ _Signal berbasis AI "
        "(SMC), bukan jaminan profit._",

        "_Selalu gunakan money management pribadi._",

        "",

        "🤖 _Signal ini dihasilkan "
        "oleh AI Agent Gold_",
    ]

    return "\n".join(lines)


# =========================================================
# WRAP TEXT
# =========================================================

def _wrap_reason(
    text: str,
    width: int = 34,
) -> str:

    words = text.split(" ")

    lines = []

    current = ""

    for word in words:

        if (
            len(current)
            + len(word)
            + 1
            > width
        ):

            if current:

                lines.append(
                    current
                )

            current = word

        else:

            current = (
                f"{current} {word}"
            ).strip()

    if current:

        lines.append(
            current
        )

    return "\n   ".join(lines)
