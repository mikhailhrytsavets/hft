"""Performance metric helpers."""

from __future__ import annotations

from typing import Sequence, Iterable, Mapping
import statistics


def sharpe(values: Sequence[float]) -> float:
    """Return simple Sharpe ratio of ``values`` list."""
    if len(values) < 2:
        return 0.0
    returns = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    if not returns:
        return 0.0
    mean = statistics.mean(returns)
    sd = statistics.stdev(returns) if len(returns) > 1 else 0.0
    return 0.0 if sd == 0 else mean / sd


def profit_factor(trades: Iterable[Mapping[str, float]]) -> float:
    """Return profit factor from an iterable of trades with ``pnl`` field."""
    gains = 0.0
    losses = 0.0
    for t in trades:
        pnl = float(t.get("pnl", 0.0))
        if pnl >= 0:
            gains += pnl
        else:
            losses -= pnl
    return gains / losses if losses else float("inf")


def max_drawdown(values: Sequence[float]) -> float:
    """Return the maximum drawdown for ``values`` list."""
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd
