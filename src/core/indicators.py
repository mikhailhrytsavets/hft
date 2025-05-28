from __future__ import annotations
from typing import Sequence, Tuple

__all__ = [
    "compute_rsi",
    "compute_adx_info",
    "compute_adx",
    "bollinger",
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
