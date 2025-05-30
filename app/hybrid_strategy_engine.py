"""Hybrid strategy engine combining SymbolEngine with extra filters."""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Optional

from app.symbol_engine import SymbolEngine
from app.exchange import BybitClient
from app.risk import RiskManager
from app.ml_model import MLModel
from app.config import settings


class HybridStrategyEngine(SymbolEngine):
    """SymbolEngine extended with market making and stat-arb logic."""

    def __init__(self, symbol: str, ref_symbol: Optional[str] = None) -> None:
        super().__init__(symbol)
        self.ref_symbol = ref_symbol
        self.mm_active: bool = False
        self.stat_arb_active: bool = False
        use_ml = getattr(settings.trading, "use_ml_scoring", False)
        self.ml_model = MLModel() if use_ml else None
        self.trade_count = 0

        self.ref_price: float | None = None
        self.spread_history: deque[float] = deque(maxlen=30)

        self.buy_order_id: Optional[str] = None
        self.sell_order_id: Optional[str] = None
        self.mm_order_time = 0.0

        if ref_symbol:
            self.ref_client = BybitClient(
                ref_symbol,
                api_key=self.client.http.api_key,
                api_secret=self.client.http.api_secret,
                testnet=self.client.http.testnet,
                demo=self.client.http.demo,
                channel_type=self.client.channel_type,
                place_orders=self.client.place_orders,
            )
            self.ref_risk = RiskManager(ref_symbol)
        else:
            self.ref_client = None
            self.ref_risk = None

    # ------------------------------------------------------------------
    def _on_ref_trades(self, symbol: str, data):
        if data:
            last = data[-1]
            try:
                self.ref_price = float(last["p"])
            except (KeyError, TypeError, ValueError):
                pass

    def _on_orderbook(self, data) -> None:  # override to track mid price
        super()._on_orderbook(data)
        bids, asks = data.get("b", []), data.get("a", [])
        if bids and asks:
            self.mid_price = (float(bids[0][0]) + float(asks[0][0])) / 2

    def _on_trades(self, data) -> None:  # keep spread history
        super()._on_trades(data)
        if self.ref_price is None or not data:
            return
        last_price = float(data[-1]["p"])
        log_ratio = math.log(last_price) - math.log(self.ref_price)
        self.spread_history.append(log_ratio)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _momentum_ok(self, direction: str) -> bool:
        if not self.market.price_window:
            return True
        period = getattr(settings.trading, "momentum_period", 5)
        if len(self.market.price_window) < period:
            return True
        now = self.market.price_window[-1]
        prev = self.market.price_window[-period]
        if direction == "LONG":
            return now >= prev
        if direction == "SHORT":
            return now <= prev
        return True

    def _ml_evaluate_signal(self, feats: list[float] | tuple[float, ...] = ()) -> bool:
        if not self.ml_model:
            return True
        return self.ml_model.allow(feats)

    # ------------------------------------------------------------------
    async def _place_mm_orders(self, mid: float) -> None:
        spread = settings.trading.mm_spread_percent / 100 * mid
        bid = mid - spread
        ask = mid + spread
        step = self.precision.step(self.client.http, self.symbol)
        self.mm_order_time = time.time()
        try:
            bid_qty = max(step, math.ceil((5 / bid) / step) * step)
            ask_qty = max(step, math.ceil((5 / ask) / step) * step)
            # qty comes first, then price
            self.buy_order_id = (
                await self.client.create_limit_order("Buy", bid_qty, bid)
            ).get("result", {}).get("orderId")
            self.sell_order_id = (
                await self.client.create_limit_order("Sell", ask_qty, ask)
            ).get("result", {}).get("orderId")
        except Exception as exc:
            print(f"[{self.symbol}] MM order error: {exc}")

    async def _refresh_mm(self) -> None:
        if not hasattr(self, "mid_price"):
            return
        if time.time() - self.mm_order_time >= settings.trading.mm_refresh_seconds:
            await self._cancel_all_active_orders()
            await self._place_mm_orders(self.mid_price)

    # ------------------------------------------------------------------
    async def run(self) -> None:
        print(f"🚀 Starting HybridStrategyEngine for {self.symbol} (ref {self.ref_symbol})")
        if self.ref_symbol:
            asyncio.create_task(BybitClient.ws_multi([self.ref_symbol], "publicTrade", self._on_ref_trades))
            while self.ref_price is None:
                await asyncio.sleep(0.05)
        if getattr(settings.trading, "enable_mm", False):
            self.mm_active = True
        if getattr(settings.trading, "enable_stat_arb", False) and self.ref_symbol:
            self.stat_arb_active = True
        await super().run()

    # ------------------------------------------------------------------
    async def _manage_position(self, price: float) -> None:
        await super()._manage_position(price)
        if self.mm_active:
            await self._refresh_mm()

    async def _open_position(self, direction: str, price: float) -> None:
        await super()._open_position(direction, price)
        self.trade_count += 1

