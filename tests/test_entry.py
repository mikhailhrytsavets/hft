from collections import deque, namedtuple

from src.strategy.entry import BounceEntry, EntrySignal

Bar = namedtuple("Bar", "open high low close volume")

def pinbar(long: bool = True) -> Bar:
    if long:
        return Bar(10, 10.1, 9.6, 10, 100)
    return Bar(10, 10.4, 9.9, 9.9, 100)


def test_full_long_signal():
    bars = deque([pinbar()] * 19, maxlen=20)
    vols = deque([50] * 19, maxlen=20)
    bars.append(pinbar())
    vols.append(120)

    closes = deque([10] * 30, maxlen=30)
    closes.extend([9.7] * 10)

    params = {}
    assert BounceEntry.check(bars[-1], vols, closes, params) == EntrySignal.LONG


def test_adx_block():
    closes = deque([i for i in range(50)], maxlen=50)
    bars = deque([pinbar(long=False)], maxlen=20)
    vols = deque([200] * 20, maxlen=20)
    assert BounceEntry.check(bars[-1], vols, closes, {}) is None
