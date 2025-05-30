from __future__ import annotations

import json
from pathlib import Path
from collections import deque

from src.core.data import Bar
from src.core import indicators
from src.strategy.bounce_entry import BounceEntry, EntrySignal
from src.strategy.manager import PositionManager


class BacktestEngine:
    """Offline backtesting wrapper for :class:`SymbolEngine`."""

    def __init__(self, symbol: str, equity: float = 10000.0, log_equity: bool = False) -> None:
        self.symbol = symbol
        self.start_equity = equity
        self.equity = equity
        self.log_equity = log_equity
        self.equity_curve: list[tuple[int, float]] = []

        self.position = PositionManager()
        self.highs: deque[float] = deque(maxlen=50)
        self.lows: deque[float] = deque(maxlen=50)
        self.closes: deque[float] = deque(maxlen=50)
        self.volumes: deque[float] = deque(maxlen=20)
        self.close_window: deque[float] = deque(maxlen=30)
        self.trades = 0
        self.wins = 0

    # ------------------------------------------------------------------
    async def feed_bar(self, open_: float, high: float, low: float, close: float, volume: float, ts: int) -> None:
        bar = Bar(open_, high, low, close, volume, ts, ts + 300)
        await self.on_bar(bar)

    async def on_bar(self, bar: Bar) -> None:
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.volumes.append(bar.volume)
        self.close_window.append(bar.close)

        atr_v = indicators.atr(list(self.highs), list(self.lows), list(self.closes), 14)

        signal = BounceEntry.check(bar, self.volumes, self.close_window, {})
        if self.position.state.qty == 0 and signal is not None:
            side = signal.value
            self.position.open(side, qty=1, entry=bar.close, atr=atr_v or 1)
            self.trades += 1
            return

        if self.position.state.qty > 0:
            result = self.position.on_tick(bar.close)
            if result in {"SL", "TRAIL"}:
                pnl = (bar.close - self.position.state.entry)
                if self.position.state.side == "SHORT":
                    pnl = -pnl
                pnl *= self.position.initial_qty
                self.equity += pnl
                if pnl > 0:
                    self.wins += 1
            elif result in {"TP1", "TP2"}:
                pnl = (bar.close - self.position.state.entry)
                if self.position.state.side == "SHORT":
                    pnl = -pnl
                pnl *= self.position.closed_qty
                self.equity += pnl

        if self.log_equity:
            self.equity_curve.append((bar.start, self.equity))

    # ------------------------------------------------------------------
    def save_equity_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for ts, eq in self.equity_curve:
                f.write(f"{ts},{eq}\n")

    def summary(self) -> dict:
        win_rate = (self.wins / self.trades * 100) if self.trades else 0.0
        return {
            "symbol": self.symbol,
            "trades": self.trades,
            "win_rate": win_rate,
            "day_pnl": self.equity - self.start_equity,
        }

