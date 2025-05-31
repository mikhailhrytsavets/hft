import types
import pytest

np = pytest.importorskip("numpy")

from app.strategy.mean_reversion import signal_long


def test_signal_long():
    closes = np.array(list(range(110, 91, -1)) + [80], dtype=float)
    bar = types.SimpleNamespace(close=closes[-1], volume=200)
    assert signal_long(bar, closes, bb_dev=2.0, rsi_low=30)

