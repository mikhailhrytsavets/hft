"""Hedging helpers implementing volume ratios and trigger rules."""

from __future__ import annotations

from typing import Tuple

# Volume-ratio mapping for hedge counterparties
HEDGE_TABLE: dict[str, Tuple[str, float]] = {
    "BTCUSDT": ("ETHUSDT", 0.50),
    "ETHUSDT": ("BTCUSDT", 0.50),
    "1000PEPEUSDT": ("BTCUSDT", 0.30),
    "default": ("BTCUSDT", 0.50),
}


def counterpart(symbol: str) -> tuple[str, float]:
    """Return hedge symbol and volume ratio for ``symbol``."""
    return HEDGE_TABLE.get(symbol, HEDGE_TABLE["default"])


def should_open(
    side: str,
    adx_now: float,
    adx_prev: float,
    dd_abs: float,
    atr: float,
    rsi: float,
) -> bool:
    """Return ``True`` if a hedge position should be opened."""
    if not (adx_now >= 30 and adx_now > adx_prev):
        return False
    if dd_abs < 1.5 * atr:
        return False
    if side == "LONG" and rsi >= 20:
        return False
    if side == "SHORT" and rsi <= 80:
        return False
    return True


def should_close(
    pnl: float,
    atr: float,
    adx_now: float,
    rsi: float,
    side: str,
) -> bool:
    """Return ``True`` if an active hedge should be closed."""
    if pnl >= +1 * atr:
        return True
    if adx_now < 25:
        return True
    if side == "LONG" and rsi >= 25:
        return True
    if side == "SHORT" and rsi <= 75:
        return True
    return False
