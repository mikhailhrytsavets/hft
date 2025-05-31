from collections import namedtuple
from legacy.strategy.bounce_entry import BounceEntry, EntrySignal, is_reversal_candle

Bar = namedtuple("Bar", "open high low close volume")


def test_long_signal_all_conditions():
    bar = Bar(10, 10.1, 9.5, 9.6, 300)
    vol_window = [100] * 19 + [300]
    bb = (9.6, 10.4)  # lower, upper
    rsi_params = (20.0, 30.0, 70.0)  # value, low_thr, high_thr
    sig = BounceEntry.generate_signal(bar, vol_window, bb, rsi_params, adx=15)
    assert sig is EntrySignal.LONG


def test_is_reversal():
    assert is_reversal_candle(10, 10.2, 9.5, 9.6)
