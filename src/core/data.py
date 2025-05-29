import asyncio
from collections import namedtuple
from typing import Awaitable, Callable, List

Bar = namedtuple("Bar", "open high low close volume start end")

class OHLCCollector:
    """Collect trades into fixed 5m OHLCV bars."""

    def __init__(self, interval: int = 300) -> None:
        self.interval = interval
        self._callbacks: List[Callable[[Bar], Awaitable[None]]] = []
        self._bar: Bar | None = None

    def subscribe(self, cb: Callable[[Bar], Awaitable[None]]) -> None:
        self._callbacks.append(cb)

    def _emit(self, bar: Bar) -> None:
        for cb in self._callbacks:
            asyncio.create_task(cb(bar))

    @property
    def last_bar(self) -> Bar | None:
        return self._bar

    def on_trade(self, price: float, qty: float, ts: int) -> None:
        """Feed a trade tick (timestamp in seconds)."""
        bucket = ts - ts % self.interval
        if self._bar is None:
            self._bar = Bar(price, price, price, price, qty, bucket, bucket + self.interval)
            return
        if bucket != self._bar.start:
            bar = self._bar._replace(end=self._bar.start + self.interval)
            self._emit(bar)
            self._bar = Bar(price, price, price, price, qty, bucket, bucket + self.interval)
            return
        open_, high, low, close, vol, start, end = self._bar
        high = max(high, price)
        low = min(low, price)
        close = price
        vol += qty
        self._bar = Bar(open_, high, low, close, vol, start, end)


"""
>>> out = []
>>> async def cb(bar):
...     out.append(bar)
>>> c = OHLCCollector()
>>> c.subscribe(cb)
>>> for p,q,t in [(10,1,0),(12,1,60),(9,2,299),(11,1,300)]:
...     c.on_trade(p,q,t)
>>> import asyncio; asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
>>> len(out)
1
>>> out[0]
Bar(open=10, high=12, low=9, close=9, volume=4, start=0, end=300)
"""
