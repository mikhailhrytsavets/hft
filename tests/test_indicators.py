import numpy as np
from src.core import indicators


def test_atr_constant_range():
    high = np.arange(1, 16, dtype=float)
    low = high - 1.5
    close = (high + low) / 2
    atr = indicators.atr(high, low, close, period=14)
    assert round(float(atr), 4) == 1.5


def test_rsi_extreme():
    # strictly increasing prices -> RSI close to 100
    closes = np.arange(0, 20, dtype=float)
    val = indicators.rsi(closes, period=14)
    assert val > 90
