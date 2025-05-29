"""Simplified symbol engine used for tests and examples."""

from collections import deque
from typing import Deque

from src.core.data import OHLCCollector, Bar
from src.market_features import MarketFeatures
from src.core import indicators
from src.strategy.bounce_entry import BounceEntry, EntrySignal
from src.strategy.dca import SmartDCA

class SymbolEngine:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.ohlc = OHLCCollector()
        self.market = MarketFeatures()
        self.ohlc.subscribe(self._on_bar)
        self.highs: Deque[float] = deque(maxlen=50)
        self.lows: Deque[float] = deque(maxlen=50)
        self.closes: Deque[float] = deque(maxlen=50)
        self.volumes: Deque[float] = deque(maxlen=20)
        self.position: dict | None = None

    async def _on_bar(self, bar: Bar) -> None:
        await self.market.on_bar(bar)
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)

        atr_v = indicators.atr(self.highs, self.lows, self.closes, period=14)
        rsi_v = indicators.rsi(self.closes, period=14)
        bb_lower, _, bb_upper = indicators.bollinger(self.closes, period=20, dev=2.0)
        adx_v = indicators.adx(self.highs, self.lows, self.closes, period=14)

        sig = BounceEntry.generate_signal(
            bar,
            list(self.volumes),
            (bb_lower, bb_upper),
            (rsi_v, 30.0, 70.0),
            adx_v,
        )

        if self.position is None and sig in (EntrySignal.LONG, EntrySignal.SHORT):
            self.position = {
                "side": "LONG" if sig is EntrySignal.LONG else "SHORT",
                "entry": bar.close,
                "fills": 0,
            }
        elif self.position is not None:
            side = self.position["side"]
            if SmartDCA.allowed(
                self.position["fills"],
                self.symbol,
                risk_pct_after_fill=1.0,
                adx=adx_v,
                rsi=rsi_v,
                spread_z=self.market.spread_z,
                vbd=self.market.vbd,
                side=side,
            ):
                target = SmartDCA.next_price(
                    self.position["entry"], atr_v, self.position["fills"] + 1, self.symbol, side
                )
                if (side == "LONG" and bar.close <= target) or (
                    side == "SHORT" and bar.close >= target
                ):
                    self.position["fills"] += 1
