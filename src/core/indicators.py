from __future__ import annotations
"""Indicator utilities used across the project."""

from typing import Sequence, Tuple
import numpy as np

# ---------------------------------------------------------------------------
# PHASE 1 AUDIT SUMMARY
# ---------------------------------------------------------------------------
# - ``src/core/indicators.py`` exists but functions are implemented with Python
#   loops rather than NumPy vectorisation.
# - ``src/strategy/entry.py`` implements ``BounceEntry`` and
#   ``is_reversal_candle`` but file name differs from the desired
#   ``bounce_entry.py``.
# - ``src/strategy/dca.py`` already provides ``SmartDCA`` with ATR based step
#   calculation and several filters.
# - ``src/risk/guard.py`` defines ``RiskGuard`` though it lacks drawdown and
#   profit lock logic.
# - ``src/symbol_engine.py`` is a minimal stub and does not integrate the
#   strategy modules.
# - ``app/settings.py`` contains ``SymbolParams`` with ``atr_period``,
#   ``bb_dev``, ``dca_max`` and ``hedge_ratio`` fields.
# - The ``tests/`` package covers indicators, entry logic, DCA and the position
#   manager.
#
# TODO (Phase 2):
#   * Vectorise indicator functions with NumPy.
#   * Provide ``strategy/bounce_entry.py`` module with ``generate_signal``.
#   * Extend ``RiskGuard`` with daily PnL tracking and drawdown/profit locks.
#   * Integrate ``SymbolEngine`` with ``BounceEntry``/``SmartDCA``/hedge logic.
#   * Ensure new unit tests for indicators, entry, dca, guard and manager.
# ---------------------------------------------------------------------------

__all__ = [
    "compute_rsi",
    "compute_adx_info",
    "compute_adx",
    "bollinger",
    "atr",
    "adx",
    "rsi",
]


def compute_rsi(closes: Sequence[float], period: int) -> float | None:
    """Return RSI calculated using Wilder smoothing."""
    if len(closes) < period + 1:
        return None
    arr = np.asarray(closes, dtype=float)
    diff = np.diff(arr)
    gain = np.clip(diff, 0, None)
    loss = np.clip(-diff, 0, None)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    for g, l in zip(gain[period:], loss[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def compute_adx_info(
    closes: Sequence[float], period: int
) -> Tuple[float | None, float | None, float | None]:
    """Return ADX together with +DI and -DI using Wilder smoothing."""
    if len(closes) < period * 2:
        return None, None, None

    arr = np.asarray(closes, dtype=float)
    diff = np.diff(arr)
    up = np.clip(diff, 0, None)
    down = np.clip(-diff, 0, None)
    tr = np.abs(diff)

    atr = tr[:period].sum()
    plus_dm = up[:period].sum()
    minus_dm = down[:period].sum()
    if atr == 0:
        return 0.0, 0.0, 0.0
    plus_di = 100 * plus_dm / atr
    minus_di = 100 * minus_dm / atr
    di_sum = plus_di + minus_di
    dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
    adx = dx

    for i in range(period, len(tr)):
        atr = atr - (atr / period) + tr[i]
        plus_dm = plus_dm - (plus_dm / period) + up[i]
        minus_dm = minus_dm - (minus_dm / period) + down[i]
        plus_di = 100 * plus_dm / atr if atr else 0.0
        minus_di = 100 * minus_dm / atr if atr else 0.0
        di_sum = plus_di + minus_di
        dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
        adx = (adx * (period - 1) + dx) / period

    return adx, plus_di, minus_di


def compute_adx(closes: Sequence[float], period: int) -> float | None:
    adx, _, _ = compute_adx_info(closes, period)
    return adx


def bollinger(
    closes: Sequence[float], period: int, dev: float
) -> Tuple[float | None, float | None, float | None]:
    """Return lower/middle/upper Bollinger band."""
    if len(closes) < period:
        return None, None, None
    arr = np.asarray(closes, dtype=float)
    subset = arr[-period:]
    mean = float(subset.mean())
    sd = float(subset.std())
    lower = mean - dev * sd
    upper = mean + dev * sd
    return lower, mean, upper


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> float:
    """Return the latest ATR value using Wilder smoothing."""
    if len(closes) < period + 1:
        return 0.0
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    tr = np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - c[:-1]),
        np.abs(l[1:] - c[:-1]),
    ])
    atr_v = tr[:period].mean()
    for val in tr[period:]:
        atr_v = (atr_v * (period - 1) + val) / period
    return float(atr_v)


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> float:
    """Return the latest ADX value using Wilder smoothing."""
    if len(closes) < period + 1:
        return 0.0
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)

    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - c[:-1]),
        np.abs(l[1:] - c[:-1]),
    ])

    atr = tr[:period].sum()
    pdm = plus_dm[:period].sum()
    mdm = minus_dm[:period].sum()
    if atr == 0:
        return 0.0
    plus_di = 100 * pdm / atr
    minus_di = 100 * mdm / atr
    di_sum = plus_di + minus_di
    dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
    adx_val = dx
    for i in range(period, len(tr)):
        atr = atr - (atr / period) + tr[i]
        pdm = pdm - (pdm / period) + plus_dm[i]
        mdm = mdm - (mdm / period) + minus_dm[i]
        plus_di = 100 * pdm / atr if atr else 0.0
        minus_di = 100 * mdm / atr if atr else 0.0
        di_sum = plus_di + minus_di
        dx = 0.0 if di_sum == 0 else abs(plus_di - minus_di) / di_sum * 100
        adx_val = (adx_val * (period - 1) + dx) / period
    return float(adx_val)


def rsi(closes: Sequence[float], period: int) -> float:
    """Return the latest RSI value."""
    val = compute_rsi(closes, period)
    return 0.0 if val is None else val
