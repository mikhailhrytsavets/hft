# Refactored on 2024-06-06 to remove legacy coupling
from __future__ import annotations

from typing import Awaitable, Callable, Deque, List, Optional, AsyncIterator
import asyncio
from collections import deque, namedtuple


Bar = namedtuple("Bar", "open high low close volume start end")


class OHLCCollector:
    """Collect trades into fixed interval OHLCV bars."""

    def __init__(self, interval: int = 300) -> None:
        self.interval = interval
        self._callbacks: List[Callable[[Bar], Awaitable[None]]] = []
        self._bar: Optional[Bar] = None

    def subscribe(self, cb: Callable[[Bar], Awaitable[None]]) -> None:
        self._callbacks.append(cb)

    def _emit(self, bar: Bar) -> None:
        for cb in self._callbacks:
            asyncio.create_task(cb(bar))

    @property
    def last_bar(self) -> Optional[Bar]:
        return self._bar

    def on_trade(self, price: float, qty: float, ts: int) -> None:
        bucket = ts - ts % self.interval
        if self._bar is None:
            self._bar = Bar(price, price, price, price, qty, bucket, bucket + self.interval)
            return
        if bucket != self._bar.start:
            bar = self._bar
            self._emit(bar)
            self._bar = Bar(price, price, price, price, qty, bucket, bucket + self.interval)
            return
        o, h, l, c, v, s, e = self._bar
        h = max(h, price)
        l = min(l, price)
        c = price
        v += qty
        self._bar = Bar(o, h, l, c, v, s, e)


async def data_stream(symbol: str) -> AsyncIterator[Bar]:
    """Placeholder async generator for live market data."""
    raise NotImplementedError("WebSocket streaming not implemented")
