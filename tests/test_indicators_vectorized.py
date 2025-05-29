import time
import pytest
np = pytest.importorskip("numpy")
from src.core import indicators


def slow_rsi(closes, period):
    if len(closes) < period + 1:
        return None
    arr = [float(c) for c in closes]
    diff = [arr[i + 1] - arr[i] for i in range(len(arr) - 1)]
    gain = [d if d > 0 else 0.0 for d in diff]
    loss = [-d if d < 0 else 0.0 for d in diff]
    avg_gain = sum(gain[:period]) / period
    avg_loss = sum(loss[:period]) / period
    for g, l in zip(gain[period:], loss[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def slow_atr(highs, lows, closes, period):
    if len(closes) < period + 1:
        return 0.0
    tr = [max(h[i] - l[i], abs(h[i] - closes[i - 1]), abs(l[i] - closes[i - 1])) for i in range(1, len(closes))]
    atr_v = sum(tr[:period]) / period
    for val in tr[period:]:
        atr_v = (atr_v * (period - 1) + val) / period
    return float(atr_v)


def slow_adx(highs, lows, closes, period):
    if len(closes) < period + 1:
        return 0.0
    up_move = [highs[i] - highs[i - 1] for i in range(1, len(highs))]
    down_move = [lows[i - 1] - lows[i] for i in range(1, len(lows))]
    plus_dm = [um if um > dm and um > 0 else 0.0 for um, dm in zip(up_move, down_move)]
    minus_dm = [dm if dm > um and dm > 0 else 0.0 for um, dm in zip(up_move, down_move)]
    tr = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    atr = sum(tr[:period])
    pdm = sum(plus_dm[:period])
    mdm = sum(minus_dm[:period])
    plus_di = 100 * pdm / atr
    minus_di = 100 * mdm / atr
    di_sum = plus_di + minus_di
    dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
    adx_val = dx
    for i in range(period, len(tr)):
        atr = atr - (atr / period) + tr[i]
        pdm = pdm - (pdm / period) + plus_dm[i]
        mdm = mdm - (mdm / period) + minus_dm[i]
        plus_di = 100 * pdm / atr if atr else 0.0
        minus_di = 100 * mdm / atr if atr else 0.0
        di_sum = plus_di + minus_di
        dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
        adx_val = (adx_val * (period - 1) + dx) / period
    return float(adx_val)


def test_vectorized_close():
    rng = np.random.default_rng(0)
    closes = rng.normal(size=60)
    highs = closes + 1
    lows = closes - 1
    assert indicators.compute_rsi(closes, 14) == pytest.approx(slow_rsi(closes, 14), rel=1e-5)
    assert indicators.atr(highs, lows, closes, 14) == pytest.approx(slow_atr(highs, lows, closes, 14), rel=1e-5)
    assert indicators.adx(highs, lows, closes, 14) == pytest.approx(slow_adx(highs, lows, closes, 14), rel=1e-5)


@pytest.mark.benchmark
def test_vectorized_speed():
    n = 100000
    closes = np.linspace(1, 2, n + 1)
    highs = closes + 1
    lows = closes - 1
    t0 = time.perf_counter()
    indicators.compute_rsi(closes, 14)
    indicators.atr(highs, lows, closes, 14)
    indicators.adx(highs, lows, closes, 14)
    assert time.perf_counter() - t0 < 0.05
