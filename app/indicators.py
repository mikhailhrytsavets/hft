from __future__ import annotations

try:  # optional dependency
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
except Exception:  # pragma: no cover - numpy not available
    np = None  # type: ignore

__all__ = ["bollinger", "rsi", "atr", "compute_adx"]


def _rolling_sum(arr: np.ndarray, window: int) -> np.ndarray:
    """Return rolling sum using cumulative sums with ``np.nan`` padding."""
    if np is None:
        raise ImportError("NumPy is required for _rolling_sum")
    if window <= 0:
        raise ValueError("window must be > 0")

    arr = np.asarray(arr, dtype=float)
    csum = np.cumsum(arr, dtype=float)
    csum = np.concatenate(([0.0], csum))
    out = csum[window:] - csum[:-window]
    return np.concatenate((np.full(window, np.nan), out))


def bollinger(close: np.ndarray, period: int = 20, dev: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised Bollinger Bands."""
    if np is None:
        raise ImportError("NumPy is required for bollinger")
    close = np.asarray(close, dtype=float)
    if close.ndim != 1:
        raise ValueError("close must be 1-D")
    if period < 1 or close.size < period:
        raise ValueError("not enough data for period")

    win = sliding_window_view(close, period)
    sma = win.mean(axis=1)
    std = win.std(axis=1, ddof=0)
    mid = np.concatenate((np.full(period - 1, np.nan), sma))
    upper = np.concatenate((np.full(period - 1, np.nan), sma + dev * std))
    lower = np.concatenate((np.full(period - 1, np.nan), sma - dev * std))
    return lower, mid, upper


def rsi(close: np.ndarray, period: int = 14) -> float:
    """Return the last RSI value."""
    if np is None:
        raise ImportError("NumPy is required for rsi")
    close = np.asarray(close, dtype=float)
    if close.ndim != 1:
        raise ValueError("close must be 1-D")
    if close.size <= period:
        raise ValueError("not enough data for period")

    diff = np.diff(close)
    gain = np.clip(diff, 0, None)
    loss = -np.clip(diff, None, 0)
    win_gain = sliding_window_view(gain, period).mean(axis=1)
    win_loss = sliding_window_view(loss, period).mean(axis=1)
    rs = np.divide(win_gain, win_loss, out=np.full_like(win_gain, np.inf), where=win_loss != 0)
    rsi_vals = 100 - 100 / (1 + rs)
    return float(rsi_vals[-1])


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    """Return the last ATR value."""
    if np is None:
        raise ImportError("NumPy is required for atr")
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    if not (high.shape == low.shape == close.shape):
        raise ValueError("high, low, close must have same shape")
    if high.ndim != 1:
        raise ValueError("inputs must be 1-D")
    if high.size <= period:
        raise ValueError("not enough data for period")

    prev_close = close[:-1]
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - prev_close),
        np.abs(low[1:] - prev_close),
    ])
    atr_vals = sliding_window_view(tr, period).mean(axis=1)
    return float(atr_vals[-1])


def compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average Directional Index (SMA style)."""
    if np is None:
        raise ImportError("NumPy is required for compute_adx")
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    if not (high.shape == low.shape == close.shape):
        raise ValueError("high, low, close must have identical shape")
    if high.ndim != 1:
        raise ValueError("inputs must be 1-D arrays")

    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close[:-1]
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - prev_close),
        np.abs(low[1:] - prev_close),
    ])

    plus_dm = np.concatenate(([0.0], plus_dm))
    minus_dm = np.concatenate(([0.0], minus_dm))
    tr = np.concatenate(([0.0], tr))

    tr_smooth = _rolling_sum(tr, period)
    plus_dm_smooth = _rolling_sum(plus_dm, period)
    minus_dm_smooth = _rolling_sum(minus_dm, period)

    plus_di = 100.0 * plus_dm_smooth / tr_smooth
    minus_di = 100.0 * minus_dm_smooth / tr_smooth

    dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = _rolling_sum(dx, period) / period
    adx[: 2 * period] = np.nan
    return adx
