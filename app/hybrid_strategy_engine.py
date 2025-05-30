import asyncio
import time
import math
import statistics
from collections import deque
from typing import Optional

from app.symbol_engine import SymbolEngine
from app.exchange import BybitClient
from app.risk import RiskManager
from app.config import settings

class HybridStrategyEngine(SymbolEngine):
    """Extended SymbolEngine with stat-arb and market-making features."""

    def __init__(self, symbol: str, ref_symbol: Optional[str] = None) -> None:
        super().__init__(symbol)
        self.ref_symbol = ref_symbol
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
        self.ref_price: float | None = None
        self.spread_history: deque[float] = deque(maxlen=200)
        # passive MM
        self.buy_order_id: Optional[str] = None
        self.sell_order_id: Optional[str] = None
        self.mm_order_time: float = 0.0
        self.mm_active: bool = False
        self.stat_arb_active: bool = False

    # ------------------------------------------------------------------
    # WebSocket handlers
    # ------------------------------------------------------------------
    def _on_ref_trades(self, symbol: str, data):
        if data:
            last = data[-1]
            try:
                self.ref_price = float(last["p"])
            except (KeyError, TypeError, ValueError):
                pass

    # ------------------------------------------------------------------
    # Helper filters
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

    def _ml_evaluate_signal(self) -> bool:
        # Placeholder for ML scoring – always allow
        print(f"[{self.symbol}] ℹ️ ML evaluate placeholder")
        return True

    # ------------------------------------------------------------------
    async def run(self) -> None:
        print(f"🚀 Starting HybridStrategyEngine for {self.symbol} (ref {self.ref_symbol})")
        if self.ref_symbol:
            asyncio.create_task(
                BybitClient.ws_multi([self.ref_symbol], "publicTrade", self._on_ref_trades)
            )
            while self.ref_price is None:
                await asyncio.sleep(0.05)
        await super().run()

