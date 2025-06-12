"""Simplified symbol engine used for tests and examples."""

from collections import deque
from typing import Deque

from legacy.core.data import OHLCCollector, Bar
from legacy.market_features import MarketFeatures
from app import indicators
from legacy.strategy.bounce_entry import BounceEntry, EntrySignal
from legacy.strategy.dca import SmartDCA
from legacy.strategy.manager import PositionManager

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
        self.pm = PositionManager()
        self.dca_fills = 0

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

        if self.pm.state.qty == 0 and sig in (EntrySignal.LONG, EntrySignal.SHORT):
            side = "LONG" if sig is EntrySignal.LONG else "SHORT"
            self.pm.open(side=side, qty=1, entry=bar.close, atr=atr_v)
            self.dca_fills = 0
        elif self.pm.state.qty > 0:
            side = self.pm.state.side or "LONG"
            if SmartDCA.allowed(
                self.dca_fills,
                self.symbol,
                risk_pct_after_fill=1.0,
                adx=adx_v,
                rsi=rsi_v,
                spread_z=self.market.spread_z,
                vbd=self.market.vbd,
                side=side,
            ):
                target = SmartDCA.next_price(
                    self.pm.state.entry, atr_v, self.dca_fills + 1, self.symbol, side
                )
                if (side == "LONG" and bar.close <= target) or (
                    side == "SHORT" and bar.close >= target
                ):
                    self.pm.add(1, bar.close)
                    self.dca_fills += 1

            self.pm.on_tick(bar.close)
            if self.pm.state.qty == 0:
                self.dca_fills = 0

