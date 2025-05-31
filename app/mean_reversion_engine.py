from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy optional
    np = None  # type: ignore
from legacy.core.indicators_vectorized import compute_adx

from app.config import settings
from app.exchange import BybitClient
from app.indicators import bollinger, rsi, atr
from app.notifier import notify_telegram
from app.risk_guard import RiskGuard
from app.strategy.mean_reversion import signal_long, signal_short, should_exit


class BaseEngine:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.client = BybitClient(
            symbol,
            api_key=settings.bybit.api_key,
            api_secret=settings.bybit.api_secret,
            testnet=settings.bybit.testnet,
            demo=settings.bybit.demo,
            channel_type=settings.bybit.channel_type,
            place_orders=settings.bybit.place_orders,
        )
        self.position_side: str | None = None
        self.position_price: float = 0.0
        self.position_qty: float = 0.0
        self.trailing_stop: float = 0.0
        self.manager: "SymbolEngineManager | None" = None

    async def run(self) -> None:
        async for price in self.client.price_stream():
            bar = SimpleNamespace(high=price, low=price, close=price, volume=1.0)
            await self.on_tick(bar)

    async def on_tick(self, bar: SimpleNamespace) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class MeanReversionEngine(BaseEngine):
    def __init__(self, symbol: str) -> None:
        super().__init__(symbol)
        self.close_win: deque[float] = deque(maxlen=20)
        self.high_win: deque[float] = deque(maxlen=20)
        self.low_win: deque[float] = deque(maxlen=20)
        self.vol_win: deque[float] = deque(maxlen=20)
        self.guard = RiskGuard(SimpleNamespace(equity_usd=0.0, open_positions=[]))

    async def on_tick(self, bar: SimpleNamespace) -> None:
        if np is None:
            return
        self.close_win.append(bar.close)
        self.high_win.append(bar.high)
        self.low_win.append(bar.low)
        self.vol_win.append(bar.volume)
        if len(self.close_win) < 20:
            return
        closes = np.array(self.close_win, dtype=float)
        highs = np.array(self.high_win, dtype=float)
        lows = np.array(self.low_win, dtype=float)
        vols = np.array(self.vol_win, dtype=float)

        bb_lower, bb_mid, bb_upper = bollinger(closes, 20, settings.trading.mr_bb_dev)
        rsi_val = rsi(closes, 14)
        atr_val = atr(highs, lows, closes, 14)
        adx_val = compute_adx(highs, lows, closes, 14)[-1]
        vol_ok = vols[-1] > 1.5 * vols.mean()

        if self.position_side is None:
            if adx_val > 25 or not vol_ok:
                return
            if signal_long(bar, closes, settings.trading.mr_bb_dev, settings.trading.mr_rsi_low):
                await self._enter("LONG", bar.close, atr_val)
            elif signal_short(bar, closes, settings.trading.mr_bb_dev, settings.trading.mr_rsi_high):
                await self._enter("SHORT", bar.close, atr_val)
            return

        # manage open position
        if should_exit(self.position_side, bar.close, bb_mid[-1], self.trailing_stop):
            await self._close()
        else:
            if self.position_side == "LONG":
                self.trailing_stop = max(self.trailing_stop, bar.close - 1.2 * atr_val)
            else:
                self.trailing_stop = min(self.trailing_stop, bar.close + 1.2 * atr_val)

    async def _enter(self, side: str, price: float, atr_val: float) -> None:
        risk_pct = 1.0
        if self.manager and not self.manager.guard.allow_new_position(risk_pct):
            return
        sl_dist = min(price * 0.015, 1.5 * atr_val)
        equity = getattr(self.manager.account, "equity_usd", 0.0) if self.manager else 0.0
        qty = (equity * risk_pct / 100) / sl_dist if sl_dist else 0.0
        self.position_side = side
        self.position_price = price
        self.position_qty = qty
        self.trailing_stop = price - 1.2 * atr_val if side == "LONG" else price + 1.2 * atr_val
        if self.manager:
            self.manager.account.open_positions.append(SimpleNamespace(symbol=self.symbol, risk_pct=risk_pct))
            self.manager.guard.inc_trade()
        await notify_telegram(f"{self.symbol} {side} entry @ {price}")

    async def _close(self) -> None:
        side = self.position_side
        if side is None:
            return
        self.position_side = None
        if self.manager:
            self.manager.position_closed(self)
        await notify_telegram(f"{self.symbol} exit @ {self.position_price}")

