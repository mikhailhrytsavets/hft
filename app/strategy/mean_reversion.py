from __future__ import annotations

from types import SimpleNamespace
try:
    import numpy as np
except Exception:  # pragma: no cover - numpy optional
    np = None  # type: ignore

from app.indicators import bollinger, rsi

__all__ = ["signal_long", "signal_short", "should_exit"]


def signal_long(bar: SimpleNamespace, window_close: np.ndarray, bb_dev: float, rsi_low: float) -> bool:
    """Return True if long entry conditions are met."""
    if np is None:
        raise ImportError("NumPy is required for signal_long")
    lower, _, _ = bollinger(window_close, period=len(window_close), dev=bb_dev)
    rsi_val = rsi(window_close, period=14)
    return bar.close < lower[-1] and rsi_val < rsi_low


def signal_short(bar: SimpleNamespace, window_close: np.ndarray, bb_dev: float, rsi_high: float) -> bool:
    """Return True if short entry conditions are met."""
    if np is None:
        raise ImportError("NumPy is required for signal_short")
    _, _, upper = bollinger(window_close, period=len(window_close), dev=bb_dev)
    rsi_val = rsi(window_close, period=14)
    return bar.close > upper[-1] and rsi_val > rsi_high


def should_exit(position_side: str, price: float, bb_mid: float, trailing_stop: float) -> bool:
    """Return True if exit conditions met."""
    if position_side == "LONG" and price >= bb_mid:
        return True
    if position_side == "SHORT" and price <= bb_mid:
        return True
    if position_side == "LONG" and price <= trailing_stop:
        return True
    if position_side == "SHORT" and price >= trailing_stop:
        return True
    return False
