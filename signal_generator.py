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
from datetime import datetime, timedelta
from typing import List, Optional

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
)


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

    recent_candles = m1_candles[-10:]

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
    # M5 STRUCTURE
    # =====================================================

    if structure_candle_count is None:

        m5_outputsize = (
            CANDLES_LOOKBACK
        )

    else:

        # Ambil beberapa candle tambahan
        # untuk memastikan candle berjalan
        # bisa dibuang.
        m5_outputsize = (
            structure_candle_count + 3
        )

    structure_candles = fetch_candles(
        interval=TF_STRUCTURE,
        outputsize=m5_outputsize,
    )

    # =====================================================
    # CHECK DATA
    # =====================================================

    required = (
        structure_candle_count
        if structure_candle_count is not None
        else CANDLES_FOR_STRUCTURE
    )

    if len(structure_candles) < required:

        raise ValueError(
            f"Data candle M5 tidak cukup. "
            f"Tersedia {len(structure_candles)}, "
            f"dibutuhkan {required}."
        )

    # =====================================================
    # MANUAL /SIGNAL
    # 12 CANDLE M5 CLOSED
    # =====================================================

    if structure_candle_count is not None:

        now = datetime.now()

        closed_candles = []

        for candle in structure_candles:

            candle_start = candle.time.replace(
                second=0,
                microsecond=0,
            )

            candle_end = (
                candle_start
                + timedelta(minutes=5)
            )

            if candle_end <= now:

                closed_candles.append(
                    candle
                )

        if len(closed_candles) < structure_candle_count:

            raise ValueError(
                "Candle M5 closed tidak cukup. "
                f"Tersedia {len(closed_candles)}, "
                f"dibutuhkan {structure_candle_count}."
            )

        structure_candles = (
            closed_candles[
                -structure_candle_count:
            ]
        )

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

    now = datetime.now()

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

        "⚠️ _Signal berbasis analisa AI "
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
