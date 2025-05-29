from __future__ import annotations
from typing import Sequence, Tuple

__all__ = [
    "compute_rsi",
    "compute_adx_info",
    "compute_adx",
    "bollinger",
    "atr",
    "adx",
    "rsi",
]


def compute_rsi(closes: Sequence[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def compute_adx_info(closes: Sequence[float], period: int) -> Tuple[float | None, float | None, float | None]:
    if len(closes) < period * 2:
        return None, None, None
    ups: list[float] = []
    downs: list[float] = []
    trs: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        ups.append(max(diff, 0.0))
        downs.append(max(-diff, 0.0))
        trs.append(abs(diff))

    atr = sum(trs[:period])
    plus_dm = sum(ups[:period])
    minus_dm = sum(downs[:period])
    if atr == 0:
        return 0.0, 0.0, 0.0
    plus_di = 100 * plus_dm / atr
    minus_di = 100 * minus_dm / atr
    di_sum = plus_di + minus_di
    dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
    adx = dx

    for i in range(period, len(trs)):
        atr = atr - (atr / period) + trs[i]
        plus_dm = plus_dm - (plus_dm / period) + ups[i]
        minus_dm = minus_dm - (minus_dm / period) + downs[i]
        plus_di = 100 * plus_dm / atr if atr else 0.0
        minus_di = 100 * minus_dm / atr if atr else 0.0
        di_sum = plus_di + minus_di
        dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
        adx = (adx * (period - 1) + dx) / period

    return adx, plus_di, minus_di


def compute_adx(closes: Sequence[float], period: int) -> float | None:
    adx, _, _ = compute_adx_info(closes, period)
    return adx


def bollinger(closes: Sequence[float], period: int, dev: float) -> Tuple[float | None, float | None]:
    if len(closes) < period:
        return None, None
    subset = closes[-period:]
    mean = sum(subset) / period
    variance = sum((c - mean) ** 2 for c in subset) / period
    sd = variance ** 0.5
    lower = mean - dev * sd
    upper = mean + dev * sd
    return lower, upper


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> float:
    """Return the latest ATR value."""
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr_v = sum(trs[:period]) / period
    for t in trs[period:]:
        atr_v = (atr_v * (period - 1) + t) / period
    return atr_v


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> float:
    """Return the latest ADX value using Wilder smoothing."""
    if len(closes) < period + 1:
        return 0.0
    tr_list: list[float] = []
    plus_dm_list: list[float] = []
    minus_dm_list: list[float] = []
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm_list.append(max(up_move if up_move > down_move and up_move > 0 else 0.0, 0.0))
        minus_dm_list.append(max(down_move if down_move > up_move and down_move > 0 else 0.0, 0.0))
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)
    atr_val = sum(tr_list[:period])
    plus_dm = sum(plus_dm_list[:period])
    minus_dm = sum(minus_dm_list[:period])
    if atr_val == 0:
        return 0.0
    plus_di = 100 * plus_dm / atr_val
    minus_di = 100 * minus_dm / atr_val
    di_sum = plus_di + minus_di
    dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
    adx_val = dx
    for i in range(period, len(tr_list)):
        atr_val = atr_val - (atr_val / period) + tr_list[i]
        plus_dm = plus_dm - (plus_dm / period) + plus_dm_list[i]
        minus_dm = minus_dm - (minus_dm / period) + minus_dm_list[i]
        plus_di = 100 * plus_dm / atr_val if atr_val else 0.0
        minus_di = 100 * minus_dm / atr_val if atr_val else 0.0
        di_sum = plus_di + minus_di
        dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
        adx_val = (adx_val * (period - 1) + dx) / period
    return adx_val


def rsi(closes: Sequence[float], period: int) -> float:
    """Return the latest RSI value."""
    val = compute_rsi(closes, period)
    return 0.0 if val is None else val
