from __future__ import annotations
"""Indicator utilities used across the project."""

from typing import Sequence, Tuple
import statistics

try:  # optional NumPy dependency
    import numpy as np
except Exception:  # pragma: no cover - fallback when numpy missing
    np = None

try:
    from .indicators_vectorized import (
        compute_rsi as _vec_compute_rsi,
        atr as _vec_atr,
        compute_adx as _vec_compute_adx,
        _rolling_sum as _vec_roll_sum,
    )
except Exception:  # pragma: no cover - when numpy missing / import fail
    _vec_compute_rsi = None  # type: ignore
    _vec_atr = None  # type: ignore
    _vec_compute_adx = None  # type: ignore
    _vec_roll_sum = None  # type: ignore

# ---------------------------------------------------------------------------
# PHASE 1 AUDIT SUMMARY
# ---------------------------------------------------------------------------
# - ``src/core/indicators.py`` exists but functions are implemented with Python
#   loops rather than NumPy vectorisation.
# - ``src/strategy/bounce_entry.py`` implements ``BounceEntry`` and
#   ``is_reversal_candle``.
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
    if np is not None and _vec_compute_rsi is not None:
        arr = _vec_compute_rsi(np.asarray(closes, dtype=float), period)
        val = arr[-1]
        return None if np.isnan(val) else float(val)

    if np is not None:
        arr = np.asarray(closes, dtype=float)
        diff = np.diff(arr)
        gain = np.where(diff > 0, diff, 0.0)
        loss = np.where(diff < 0, -diff, 0.0)
    else:
        arr = [float(c) for c in closes]
        diff = [arr[i + 1] - arr[i] for i in range(len(arr) - 1)]
        gain = [d if d > 0 else 0.0 for d in diff]
        loss = [-d if d < 0 else 0.0 for d in diff]
    avg_gain = sum(gain[:period]) / period
    avg_loss = sum(loss[:period]) / period
    for g, loss_val in zip(gain[period:], loss[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss_val) / period
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

    if np is not None:
        arr = np.asarray(closes, dtype=float)
        diff = np.diff(arr)
        up = np.where(diff > 0, diff, 0.0)
        down = np.where(diff < 0, -diff, 0.0)
        tr = np.abs(diff)
    else:
        arr = [float(c) for c in closes]
        diff = [arr[i + 1] - arr[i] for i in range(len(arr) - 1)]
        up = [d if d > 0 else 0.0 for d in diff]
        down = [-d if d < 0 else 0.0 for d in diff]
        tr = [abs(d) for d in diff]

    atr = sum(tr[:period])
    plus_dm = sum(up[:period])
    minus_dm = sum(down[:period])
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
    if np is not None:
        subset = np.asarray(closes[-period:], dtype=float)
        mean = float(np.mean(subset))
        sd = float(np.std(subset, ddof=1)) if period > 1 else 0.0
    else:
        subset = [float(c) for c in closes[-period:]]
        mean = statistics.mean(subset)
        sd = statistics.stdev(subset) if period > 1 else 0.0
    lower = mean - dev * sd
    upper = mean + dev * sd
    return lower, mean, upper


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> float:
    """Return the latest ATR value using Wilder smoothing."""
    if len(closes) < period + 1:
        return 0.0
    if np is not None and _vec_atr is not None:
        arr = _vec_atr(
            np.asarray(highs, dtype=float),
            np.asarray(lows, dtype=float),
            np.asarray(closes, dtype=float),
            period,
        )
        val = arr[-1]
        return 0.0 if np.isnan(val) else float(val)

    if np is not None:
        h = np.asarray(highs, dtype=float)
        low_arr = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)
        tr = h[1:] - low_arr[1:]
    else:
        h = [float(x) for x in highs]
        low_arr = [float(x) for x in lows]
        c = [float(x) for x in closes]
        tr = [h[i] - low_arr[i] for i in range(1, len(c))]
    atr_v = sum(tr[:period]) / period
    for val in tr[period:]:
        atr_v = (atr_v * (period - 1) + val) / period
    return float(atr_v)


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> float:
    """Return the latest ADX value using Wilder smoothing."""
    if len(closes) < period + 1:
        return 0.0
    if np is not None and _vec_compute_adx is not None:
        arr = _vec_compute_adx(
            np.asarray(highs, dtype=float),
            np.asarray(lows, dtype=float),
            np.asarray(closes, dtype=float),
            period,
        )
        val = arr[-1]
        return 0.0 if np.isnan(val) else float(val)

    if np is not None:
        h = np.asarray(highs, dtype=float)
        low_arr = np.asarray(lows, dtype=float)
        c = np.asarray(closes, dtype=float)

        up_move = h[1:] - h[:-1]
        down_move = low_arr[:-1] - low_arr[1:]
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr = np.maximum.reduce([
            h[1:] - low_arr[1:],
            np.abs(h[1:] - c[:-1]),
            np.abs(low_arr[1:] - c[:-1]),
        ])
    else:
        h = [float(x) for x in highs]
        low_arr = [float(x) for x in lows]
        c = [float(x) for x in closes]

        up_move = [h[i] - h[i - 1] for i in range(1, len(h))]
        down_move = [low_arr[i - 1] - low_arr[i] for i in range(1, len(low_arr))]
        plus_dm = [um if um > dm and um > 0 else 0.0 for um, dm in zip(up_move, down_move)]
        minus_dm = [dm if dm > um and dm > 0 else 0.0 for um, dm in zip(up_move, down_move)]
        tr = [
            max(h[i] - low_arr[i], abs(h[i] - c[i - 1]), abs(low_arr[i] - c[i - 1]))
            for i in range(1, len(c))
        ]

    atr = sum(tr[:period])
    pdm = sum(plus_dm[:period])
    mdm = sum(minus_dm[:period])
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
