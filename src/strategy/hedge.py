from __future__ import annotations
from typing import Literal, Tuple

HEDGE_MAP: dict[str, Tuple[str, float]] = {
    "BTCUSDT": ("ETHUSDT", 0.50),
    "ETHUSDT": ("BTCUSDT", 0.50),
    "1000PEPEUSDT": ("BTCUSDT", 0.30),
    "default": ("BTCUSDT", 0.50),
}

class HedgeGuard:
    """Mixin implementing simple hedge logic."""

    hedge_active: bool = False
    _prev_adx: float = 0.0

    async def maybe_hedge(
        self,
        pos,
        adx_now: float,
        atr: float,
        rsi: float,
    ) -> None:
        adx_prev = self._prev_adx
        self._prev_adx = adx_now
        if (
            adx_now >= 30 and adx_now > adx_prev and
            abs(self.unrealised_dd) > 1.5 * atr and
            ((pos.side == "LONG" and rsi < 20) or (pos.side == "SHORT" and rsi > 80)) and
            not self.hedge_active
        ):
            hedge_sym, ratio = HEDGE_MAP.get(pos.symbol, HEDGE_MAP["default"])
            qty = pos.notional_value * ratio / self._last_price(hedge_sym)
            side = "SHORT" if pos.side == "LONG" else "LONG"
            await self._open_hedge(hedge_sym, qty, side)
            self.hedge_active = True

        if self.hedge_active:
            pnl = self._hedge_pnl()
            if (
                pnl >= atr * 1 or
                adx_now < 25 or
                (pos.side == "LONG" and rsi > 25) or
                (pos.side == "SHORT" and rsi < 75)
            ):
                await self._close_hedge()
                self.hedge_active = False
