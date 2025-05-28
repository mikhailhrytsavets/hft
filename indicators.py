from typing import List

class CandleAggregator:
    """Aggregate tick prices into fixed interval candles."""

    def __init__(self, interval_sec: int = 15) -> None:
        self.interval = interval_sec
        self.reset()

    def reset(self) -> None:
        self.open = self.high = self.low = self.close = None
        self.start_ts = None

    def add_tick(self, price: float, ts: float):
        """Add a tick price with timestamp. Returns (high, low, close) when a candle closes."""
        if self.start_ts is None:
            self.start_ts = ts
            self.open = self.high = self.low = self.close = price
            return None
        if ts - self.start_ts < self.interval:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
            self.close = price
            return None
        candle = (self.high, self.low, self.close)
        self.reset()
        self.start_ts = ts
        self.open = self.high = self.low = self.close = price
        return candle

__all__ = ["CandleAggregator"]
