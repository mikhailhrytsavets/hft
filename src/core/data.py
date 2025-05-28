import asyncio
from collections import namedtuple

Bar = namedtuple("Bar", "open high low close volume start end")

class OHLCCollector:
    """Collect trades into 5-minute OHLC bars."""

    INTERVAL_MS = 5 * 60 * 1000

    def __init__(self) -> None:
        self._callbacks: list = []
        self._current: dict | None = None

    @property
    def last_bar(self) -> Bar | None:
        if self._current is None:
            return None
        return Bar(
            self._current["open"],
            self._current["high"],
            self._current["low"],
            self._current["close"],
            self._current["volume"],
            self._current["start"],
            self._current["end"],
        )

    def subscribe(self, callback) -> None:
        self._callbacks.append(callback)

    def _emit(self, bar: Bar) -> None:
        for cb in self._callbacks:
            if asyncio.iscoroutinefunction(cb):
                asyncio.create_task(cb(bar))
            else:
                cb(bar)

    def on_trade(self, price: float, qty: float, ts: int) -> None:
        bucket = (ts // self.INTERVAL_MS) * self.INTERVAL_MS
        if self._current is None:
            self._current = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
                "start": bucket,
                "end": bucket + self.INTERVAL_MS,
            }
            return

        if bucket != self._current["start"]:
            bar = self.last_bar
            self._emit(bar)
            self._current = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
                "start": bucket,
                "end": bucket + self.INTERVAL_MS,
            }
        else:
            self._current["high"] = max(self._current["high"], price)
            self._current["low"] = min(self._current["low"], price)
            self._current["close"] = price
            self._current["volume"] += qty


if __name__ == "__main__":
    import doctest
    doctest.testmod()

"""
>>> import asyncio
>>> oc = OHLCCollector()
>>> b1, b2 = [], []
>>> async def c1(bar):
...     b1.append(bar)
>>> async def c2(bar):
...     b2.append(bar)
>>> oc.subscribe(c1)
>>> oc.subscribe(c2)
>>> ts = 0
>>> for price in (100, 101, 99, 103, 104):
...     oc.on_trade(price, 1, ts)
...     ts += 60_000
>>> oc.on_trade(105, 1, ts)
>>> asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
>>> len(b1), len(b2)
(1, 1)
>>> b1[0].open, b1[0].high, b1[0].low, b1[0].close
(100, 104, 99, 104)
"""
