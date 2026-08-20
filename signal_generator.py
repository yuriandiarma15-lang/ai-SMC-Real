"""
Menggabungkan:
- Analisa struktur SMC di M5 (12 candle = 1 candle H1)
- Timing entry presisi di M1 (cari harga masuk terbaik di dalam zona OB/FVG)
- Risk management (SL 50 pip, TP1 70 pip, TP2 150 pip)

Lalu merangkai semuanya jadi objek TradeSignal + teks siap kirim ke Telegram.
"""

from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class TradeSignal:
    timestamp: datetime
    bias: str
    entry_price: float
    entry_type: str      # deskripsi singkat untuk manusia
    order_type: str       # "Market", "Buy Limit", "Sell Limit", "Buy Stop", "Sell Stop"
    is_pending: bool      # True kalau harus pasang pending order (bukan market langsung)
    sl: float
    tp1: float
    tp2: float
    probability: int
    reasons: List[str]
    smc: SMCResult
    session_name: str
    session_note: str


def _get_session_info(dt: datetime) -> tuple[str, str]:
    """Tentukan sesi trading (Asia/London/New York) berdasarkan jam WIB saat signal dibuat."""
    hour = dt.hour
    for session in SESSIONS:
        if hour in session["hours"]:
            return session["name"], session["note"]
    return "Trading", "pantau pergerakan harga dengan disiplin & manajemen risiko"


def _determine_order_type(bias: str, entry_price: float, current_price: float,
                           has_zone: bool) -> tuple[str, bool]:
    """
    Tentukan jenis order berdasarkan posisi entry_price relatif ke harga sekarang:
    - Selisih kecil (<= MARKET_ENTRY_TOLERANCE)          -> Market
    - Bullish, entry di BAWAH harga sekarang              -> Buy Limit  (nunggu retrace turun)
    - Bullish, entry di ATAS harga sekarang               -> Buy Stop   (nunggu breakout naik)
    - Bearish, entry di ATAS harga sekarang               -> Sell Limit (nunggu retrace naik)
    - Bearish, entry di BAWAH harga sekarang              -> Sell Stop  (nunggu breakout turun)
    Return: (order_type, is_pending)
    """
    if not has_zone or abs(entry_price - current_price) <= MARKET_ENTRY_TOLERANCE:
        return "Market", False

    if bias == "bullish":
        if entry_price < current_price:
            return "Buy Limit", True
        return "Buy Stop", True
    else:
        if entry_price > current_price:
            return "Sell Limit", True
        return "Sell Stop", True


def _find_entry_zone(smc: SMCResult, current_price: float):
    """
    Cari zona OB/FVG searah bias yang paling dekat dengan harga sekarang untuk dijadikan
    acuan entry limit (harga optimal secara SMC), bukan sekadar market price.
    """
    candidates = []
    for ob in smc.order_blocks:
        mid = (ob.high + ob.low) / 2
        candidates.append((abs(current_price - mid), mid, "Order Block"))
    for fvg in smc.fvgs:
        mid = (fvg.top + fvg.bottom) / 2
        candidates.append((abs(current_price - mid), mid, "Fair Value Gap"))

    if not candidates:
        return None, None

    candidates.sort(key=lambda x: x[0])
    _, price, zone_type = candidates[0]
    return price, zone_type


def _build_entry_description(order_type: str, is_pending: bool, m1_candles: List[Candle],
                              entry_price: float) -> str:
    """Deskripsi human-readable untuk baris 'Tipe entry' di pesan Telegram."""
    if not is_pending:
        return "Market (harga sudah di zona optimal)"

    recent_low = min(c.low for c in m1_candles[-10:])
    recent_high = max(c.high for c in m1_candles[-10:])
    already_touched = recent_low <= entry_price <= recent_high

    if already_touched:
        return f"Pending {order_type} (zona OB/FVG barusan sempat tersentuh)"
    return f"Pending {order_type} (pasang order, tunggu harga menuju zona OB/FVG)"


def generate_signal() -> TradeSignal:
    structure_candles = fetch_candles(interval=TF_STRUCTURE, outputsize=CANDLES_LOOKBACK)
    entry_candles = fetch_candles(interval=TF_ENTRY, outputsize=CANDLES_ENTRY_LOOKBACK)

    if len(structure_candles) < CANDLES_FOR_STRUCTURE:
        raise ValueError("Data candle M5 tidak cukup untuk analisa struktur")

    smc = analyze(structure_candles)
    current_price = entry_candles[-1].close

    zone_price, zone_type = _find_entry_zone(smc, current_price)
    has_zone = zone_price is not None

    # Entry SELALU memakai harga zona OB/FVG asli kalau ada (bukan didekatkan ke market) —
    # kalaupun H1 close jauh dari zona, kita tetap arahkan ke situ lewat pending order.
    entry_price = zone_price if has_zone else current_price

    order_type, is_pending = _determine_order_type(smc.bias, entry_price, current_price, has_zone)
    entry_type = _build_entry_description(order_type, is_pending, entry_candles, entry_price)

    if zone_type:
        smc.confluences.append(f"Entry mengacu ke {zone_type} terdekat dari harga sekarang")
    if is_pending:
        smc.confluences.append(
            f"Harga sekarang ({round(current_price, 2)}) masih berjarak dari zona optimal — "
            f"gunakan pending order, bukan market"
        )

    if smc.bias == "bullish":
        sl = entry_price - SL_DISTANCE
        tp1 = entry_price + TP1_DISTANCE
        tp2 = entry_price + TP2_DISTANCE
    else:
        sl = entry_price + SL_DISTANCE
        tp1 = entry_price - TP1_DISTANCE
        tp2 = entry_price - TP2_DISTANCE

    now = datetime.now()
    session_name, session_note = _get_session_info(now)

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
    )


def format_signal_message(sig: TradeSignal) -> str:
    """
    Format teks Telegram: baris pendek-pendek (biar tidak melebar di HP),
    pakai Markdown sederhana yang aman untuk parse_mode=Markdown.
    """
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
        f"{entry_label} : `{sig.entry_price}`",
        f"🛑 SL     : `{sig.sl}`  (-{SL_PIPS} pip)",
        f"✅ TP1    : `{sig.tp1}`  (+{TP1_PIPS} pip)",
        f"✅ TP2    : `{sig.tp2}`  (+{TP2_PIPS} pip)",
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
                f"⏳ Pasang {sig.order_type} di harga entry di atas. Kalau dalam "
                f"{PENDING_ORDER_TIMEOUT_MINUTES} menit belum kesentuh, signal ini "
                f"otomatis dianggap batal (skip, tidak perlu entry lagi)."
            ),
        ]

    lines += [
        "",
        "⚠️ _Signal berbasis analisa AI (SMC), bukan jaminan profit._",
        "_Selalu gunakan money management pribadi._",
        "",
        "🤖 _Signal ini dihasilkan oleh AI Agent Gold_",
    ]

    return "\n".join(lines)


def _wrap_reason(text: str, width: int = 34) -> str:
    """Pecah baris alasan yang panjang jadi beberapa baris pendek, biar rapi di HP."""
    words = text.split(" ")
    lines, current = [], ""
    for w in words:
        if len(current) + len(w) + 1 > width:
            lines.append(current)
            current = w
        else:
            current = f"{current} {w}".strip()
    if current:
        lines.append(current)
    return "\n   ".join(lines)
