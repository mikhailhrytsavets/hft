# Refactored on 2024-06-06 to remove legacy coupling
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class DCAFilters:
    adx_max: float = 25.0
    rsi_exit: int = 60
    spread_z_max: float = 2.0
    vbd_max: float = 0.25


class SmartDCA:
    MAX_DCA = {"BTCUSDT": 3, "ETHUSDT": 3, "1000PEPEUSDT": 1, "default": 2}

    @staticmethod
    def calc_step(n: int, atr: float, symbol: str) -> float:
        k = max(1.0, 1.2 * n)
        if symbol.startswith("1000PEPE"):
            k *= 1.3
        return k * atr

    @staticmethod
    def next_price(
        base_price: float,
        atr: float,
        n: int,
        symbol: str,
        side: Literal["LONG", "SHORT"],
    ) -> float:
        step = SmartDCA.calc_step(n, atr, symbol)
        return base_price - step if side == "LONG" else base_price + step

    @staticmethod
    def allowed(
        n: int,
        symbol: str,
        risk_pct_after_fill: float,
        adx: float,
        rsi: float,
        spread_z: float,
        vbd: float,
        side: Literal["LONG", "SHORT"] = "LONG",
        f: DCAFilters = DCAFilters(),
    ) -> bool:
        cap = SmartDCA.MAX_DCA.get(symbol, SmartDCA.MAX_DCA["default"])
        if n >= cap:
            return False
        if risk_pct_after_fill > 5.0:
            return False
        if adx >= f.adx_max:
            return False
        if abs(spread_z) > f.spread_z_max:
            return False
        if abs(vbd) > f.vbd_max:
            return False
        if side == "LONG" and rsi > f.rsi_exit and n > 0:
            return False
        if side == "SHORT" and rsi < (100 - f.rsi_exit) and n > 0:
            return False
        return True
