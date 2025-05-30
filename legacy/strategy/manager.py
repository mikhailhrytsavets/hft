"""Simple position management for backtesting."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PositionState:
    side: str | None = None
    qty: float = 0.0
    entry: float = 0.0
    atr: float = 0.0


class PositionManager:
    """Handle partial take profits and trailing stop logic."""

    def __init__(
        self,
        tp1_ratio: float = 0.4,
        tp2_ratio: float = 0.3,
        sl_atr: float = 1.5,
        tp1_atr: float = 1.0,
        tp2_atr: float = 2.0,
        trailing_pct: float = 0.2,
    ) -> None:
        self.tp1_ratio = tp1_ratio
        self.tp2_ratio = tp2_ratio
        self.sl_atr = sl_atr
        self.tp1_atr = tp1_atr
        self.tp2_atr = tp2_atr
        self.trailing_pct = trailing_pct
        self.state = PositionState()
        self.initial_qty = 0.0
        self.sl: float | None = None
        self.tp1: float | None = None
        self.tp2: float | None = None
        self.closed_qty = 0.0
        self.trailing_started = False
        self.best_price: float | None = None
        self.trail_price: float | None = None

    # ------------------------------------------------------------------
    def open(self, side: str, qty: float, entry: float, atr: float) -> None:
        """Open a new position and set TP/SL levels."""
        self.state.side = side
        self.state.qty = qty
        self.initial_qty = qty
        self.state.entry = entry
        self.state.atr = atr
        if side == "LONG":
            self.sl = entry - self.sl_atr * atr
            self.tp1 = entry + self.tp1_atr * atr
            self.tp2 = entry + self.tp2_atr * atr
        else:
            self.sl = entry + self.sl_atr * atr
            self.tp1 = entry - self.tp1_atr * atr
            self.tp2 = entry - self.tp2_atr * atr
        self.closed_qty = 0.0
        self.trailing_started = False
        self.best_price = entry
        self.trail_price = entry

    # ------------------------------------------------------------------
    def add(self, qty: float, price: float) -> None:
        """Increase position size and recalc average entry price."""
        if self.state.side is None or qty <= 0:
            return
        total = self.state.entry * self.state.qty + price * qty
        self.state.qty += qty
        self.initial_qty += qty
        self.state.entry = total / self.state.qty
        if self.state.side == "LONG":
            self.sl = self.state.entry - self.sl_atr * self.state.atr
            self.tp1 = self.state.entry + self.tp1_atr * self.state.atr
            self.tp2 = self.state.entry + self.tp2_atr * self.state.atr
        else:
            self.sl = self.state.entry + self.sl_atr * self.state.atr
            self.tp1 = self.state.entry - self.tp1_atr * self.state.atr
            self.tp2 = self.state.entry - self.tp2_atr * self.state.atr

    # ------------------------------------------------------------------
    def _close_fraction(self, frac: float) -> float:
        qty_close = min(self.state.qty, self.initial_qty * frac)
        self.state.qty -= qty_close
        self.closed_qty += qty_close
        return qty_close

    # ------------------------------------------------------------------
    def on_tick(self, price: float) -> str | None:
        """Update position state based on ``price``."""
        if self.state.side is None or self.state.qty <= 0:
            return None
        side = self.state.side

        # stop-loss -----------------------------------------------------
        if side == "LONG" and self.sl is not None and price <= self.sl:
            self._close_fraction(1.0)
            self.state.side = None
            return "SL"
        if side == "SHORT" and self.sl is not None and price >= self.sl:
            self._close_fraction(1.0)
            self.state.side = None
            return "SL"

        # TP1 -----------------------------------------------------------
        if not self.trailing_started:
            if side == "LONG" and self.tp1 is not None and price >= self.tp1:
                self._close_fraction(self.tp1_ratio)
                self.trailing_started = True
                self.best_price = price
                self.trail_price = self.state.entry
                return "TP1"
            if side == "SHORT" and self.tp1 is not None and price <= self.tp1:
                self._close_fraction(self.tp1_ratio)
                self.trailing_started = True
                self.best_price = price
                self.trail_price = self.state.entry
                return "TP1"

        # TP2 -----------------------------------------------------------
        if self.trailing_started and self.state.qty > 0:
            if side == "LONG" and self.tp2 is not None and price >= self.tp2:
                self._close_fraction(self.tp2_ratio)
                self.best_price = price
                return "TP2"
            if side == "SHORT" and self.tp2 is not None and price <= self.tp2:
                self._close_fraction(self.tp2_ratio)
                self.best_price = price
                return "TP2"

        # trailing ------------------------------------------------------
        if self.trailing_started and self.state.qty > 0:
            if side == "LONG":
                if price > (self.best_price or price):
                    self.best_price = price
                    self.trail_price = price * (1 - self.trailing_pct / 100)
                if self.trail_price is not None and price <= self.trail_price:
                    self._close_fraction(1.0)
                    self.state.side = None
                    return "TRAIL"
            else:  # SHORT
                if price < (self.best_price or price):
                    self.best_price = price
                    self.trail_price = price * (1 + self.trailing_pct / 100)
                if self.trail_price is not None and price >= self.trail_price:
                    self._close_fraction(1.0)
                    self.state.side = None
                    return "TRAIL"

        return None
