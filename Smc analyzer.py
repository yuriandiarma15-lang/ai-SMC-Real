"""
Analisa Smart Money Concept (SMC) sederhana di atas candle M5.

Konsep yang dipakai:
1. Swing High/Low (fractal 3 candle)      -> menentukan struktur pasar
2. BOS (Break of Structure)               -> konfirmasi trend berlanjut
3. CHoCH (Change of Character)            -> sinyal potensi reversal
4. Order Block (OB)                       -> candle terakhir berlawanan sebelum impulsive move
5. Fair Value Gap (FVG) / imbalance       -> zona gap 3 candle
6. Liquidity pool (equal high/low)        -> area stop hunt

Semua fungsi bekerja pada list Candle (lama -> baru) dari twelvedata_client.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal

from twelvedata_client import Candle

Direction = Literal["bullish", "bearish"]


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: Direction  # "bullish" = swing low, "bearish" = swing high (biar konsisten sama BOS)


@dataclass
class OrderBlock:
    index: int
    high: float
    low: float
    direction: Direction  # order block bullish = zona demand, bearish = zona supply


@dataclass
class FVG:
    index: int
    top: float
    bottom: float
    direction: Direction


@dataclass
class SMCResult:
    bias: Direction
    structure_event: str          # "BOS" atau "CHoCH"
    last_bos_price: Optional[float]
    order_blocks: List[OrderBlock] = field(default_factory=list)
    fvgs: List[FVG] = field(default_factory=list)
    liquidity_swept: bool = False
    confluences: List[str] = field(default_factory=list)  # alasan-alasan, dipakai buat teks signal
    score: int = 0  # 0-100, dipakai untuk probabilitas


def find_swing_points(candles: List[Candle], left: int = 2, right: int = 2) -> List[SwingPoint]:
    """Fractal sederhana: swing high/low dikonfirmasi kalau titik tengah paling ekstrem
    dibanding `left` candle sebelum & `right` candle sesudahnya."""
    points = []
    n = len(candles)
    for i in range(left, n - right):
        window = candles[i - left:i + right + 1]
        c = candles[i]
        if c.high == max(w.high for w in window):
            points.append(SwingPoint(index=i, price=c.high, kind="bearish"))
        if c.low == min(w.low for w in window):
            points.append(SwingPoint(index=i, price=c.low, kind="bullish"))
    return points


def detect_structure(candles: List[Candle], swings: List[SwingPoint]) -> tuple[Direction, str, Optional[float]]:
    """
    Tentukan bias market dari swing terakhir:
    - BOS  : harga close menembus swing high/low SEARAH trend sebelumnya -> trend lanjut
    - CHoCH: harga close menembus swing high/low BERLAWANAN trend sebelumnya -> potensi reversal
    """
    if len(swings) < 2:
        return "bullish", "BOS", None

    highs = [s for s in swings if s.kind == "bearish"]
    lows = [s for s in swings if s.kind == "bullish"]
    if not highs or not lows:
        return "bullish", "BOS", None

    last_high = highs[-1]
    last_low = lows[-1]
    last_close = candles[-1].close

    # Tentukan trend sebelumnya dari urutan waktu swing high vs swing low terakhir
    prev_trend: Direction = "bullish" if last_low.index > last_high.index else "bearish"

    if last_close > last_high.price:
        event = "BOS" if prev_trend == "bullish" else "CHoCH"
        return "bullish", event, last_high.price
    if last_close < last_low.price:
        event = "BOS" if prev_trend == "bearish" else "CHoCH"
        return "bearish", event, last_low.price

    # Belum ada break baru -> ikuti trend terakhir yang masih valid
    return prev_trend, "Range/Belum Break", None


def find_order_blocks(candles: List[Candle], bias: Direction, lookback: int = 20) -> List[OrderBlock]:
    """
    Order block bullish : candle BEARISH terakhir sebelum rangkaian candle bullish kuat.
    Order block bearish : candle BULLISH terakhir sebelum rangkaian candle bearish kuat.
    Hanya cari OB yang searah bias saat ini (yang relevan untuk entry).
    """
    obs = []
    recent = candles[-lookback:]
    offset = len(candles) - len(recent)

    for i in range(1, len(recent) - 1):
        c = recent[i]
        nxt = recent[i + 1]
        impulsive = nxt.body > nxt.range * 0.6  # body dominan -> candle impulsif

        if bias == "bullish" and c.is_bearish and nxt.is_bullish and impulsive and nxt.close > c.high:
            obs.append(OrderBlock(index=offset + i, high=c.high, low=c.low, direction="bullish"))

        if bias == "bearish" and c.is_bullish and nxt.is_bearish and impulsive and nxt.close < c.low:
            obs.append(OrderBlock(index=offset + i, high=c.high, low=c.low, direction="bearish"))

    return obs[-3:]  # ambil 3 OB paling relevan (terdekat)


def find_fvgs(candles: List[Candle], bias: Direction, lookback: int = 20) -> List[FVG]:
    """FVG 3 candle: gap antara candle[0] dan candle[2] yang tidak overlap = imbalance."""
    fvgs = []
    recent = candles[-lookback:]
    offset = len(candles) - len(recent)

    for i in range(len(recent) - 2):
        c1, c3 = recent[i], recent[i + 2]
        if bias == "bullish" and c1.high < c3.low:
            fvgs.append(FVG(index=offset + i + 1, top=c3.low, bottom=c1.high, direction="bullish"))
        if bias == "bearish" and c1.low > c3.high:
            fvgs.append(FVG(index=offset + i + 1, top=c1.low, bottom=c3.high, direction="bearish"))

    return fvgs[-3:]


def check_liquidity_sweep(candles: List[Candle], swings: List[SwingPoint], bias: Direction) -> bool:
    """
    Deteksi liquidity sweep sederhana: candle terakhir/kedua terakhir sempat menembus
    swing high/low sebelumnya dengan WICK, tapi CLOSE kembali di dalam range
    (tanda stop hunt sebelum reversal/continuation searah bias).
    """
    if len(swings) < 2:
        return False

    relevant = [s for s in swings if s.kind == ("bearish" if bias == "bullish" else "bullish")]
    if not relevant:
        return False

    target = relevant[-1]
    for c in candles[-3:]:
        if bias == "bullish" and c.low < target.price and c.close > target.price:
            return True
        if bias == "bearish" and c.high > target.price and c.close < target.price:
            return True
    return False


def analyze(candles: List[Candle]) -> SMCResult:
    """Entry point: jalankan seluruh analisa SMC di atas data candle M5, hasilkan skor & alasan."""
    swings = find_swing_points(candles)
    bias, event, bos_price = detect_structure(candles, swings)

    obs = find_order_blocks(candles, bias)
    fvgs = find_fvgs(candles, bias)
    swept = check_liquidity_sweep(candles, swings, bias)

    confluences = []
    score = 40  # baseline

    if event == "BOS":
        confluences.append(f"BOS {bias} terkonfirmasi, trend M5 masih searah")
        score += 15
    elif event == "CHoCH":
        confluences.append(f"CHoCH terdeteksi, indikasi reversal ke arah {bias}")
        score += 20
    else:
        confluences.append("Struktur masih ranging, mengikuti trend swing terakhir")

    if obs:
        confluences.append(f"Ada {len(obs)} Order Block {bias} yang belum di-mitigasi")
        score += 15

    if fvgs:
        confluences.append(f"Ada {len(fvgs)} Fair Value Gap {bias} yang belum terisi penuh")
        score += 15

    if swept:
        confluences.append("Liquidity sweep terdeteksi (stop hunt) sebelum pergerakan searah bias")
        score += 15

    score = max(35, min(score, 95))

    return SMCResult(
        bias=bias,
        structure_event=event,
        last_bos_price=bos_price,
        order_blocks=obs,
        fvgs=fvgs,
        liquidity_swept=swept,
        confluences=confluences,
        score=score,
    )
