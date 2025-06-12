from app import indicators


def test_atr_constant_range():
    high = [float(i) for i in range(1, 16)]
    low = [h - 1.5 for h in high]
    close = [(h + low_val) / 2 for h, low_val in zip(high, low)]
    atr = indicators.atr(high, low, close, period=14)
    assert round(float(atr), 4) == 1.5


def test_rsi_extreme():
    # strictly increasing prices -> RSI close to 100
    closes = [float(i) for i in range(0, 20)]
    val = indicators.rsi(closes, period=14)
    assert val > 90
