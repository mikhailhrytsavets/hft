from __future__ import annotations

import statistics
from collections import deque
from enum import Enum

from src.core.indicators import compute_rsi, compute_adx, bollinger


class EntrySignal(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


def is_reversal_candle(open_p: float, high: float, low: float, close: float) -> bool:
    """Detect a simple pin-bar or belt hold pattern."""
    rng = high - low
    if rng <= 0:
        return False
    body = abs(close - open_p)
    upper = high - max(open_p, close)
    lower = min(open_p, close) - low
    if body <= rng * 0.5 and (lower >= rng * 0.6 or upper >= rng * 0.6):
        return True
    if open_p <= low and close >= open_p + rng * 0.6:
        return True
    if open_p >= high and close <= open_p - rng * 0.6:
        return True
    return False


class BounceEntry:
    @staticmethod
    def _getter(params):
        if hasattr(params, "get"):
            return params.get
        if hasattr(params, "model_dump"):
            data = params.model_dump()
            return data.get
        return lambda k, d=None: getattr(params, k, d)

    @staticmethod
    def _params(params) -> dict:
        get = BounceEntry._getter(params)
        return {
            "bb_dev": get("bb_dev", 2.0),
            "bb_period": get("bb_period", 20),
            "rsi_period": get("rsi_period", 14),
            "rsi_extreme": get("rsi_extreme", (30.0, 70.0)),
            "adx_period": get("adx_period", 14),
            "adx_threshold": get("adx_threshold", 25.0),
        }

    @staticmethod
    def check(
        bar, volumes: deque[float], closes: deque[float], params
    ) -> EntrySignal | None:
        cfg = BounceEntry._params(params)
        if len(volumes) < cfg["bb_period"] or len(closes) < cfg["bb_period"]:
            return None

        closes_seq: list[float] = list(closes)
        lower, upper = bollinger(closes_seq, cfg["bb_period"], cfg["bb_dev"])
        if lower is None or upper is None:
            return None
        if bar.close >= lower:
            direction = EntrySignal.LONG
        elif bar.close >= upper:
            direction = EntrySignal.SHORT
        else:
            return None

        rsi = compute_rsi(closes_seq, cfg["rsi_period"])
        if rsi is None:
            return None
        low_thr, high_thr = cfg["rsi_extreme"]
        if direction == EntrySignal.LONG and rsi >= low_thr:
            return None
        if direction == EntrySignal.SHORT and rsi <= high_thr:
            return None

        if not is_reversal_candle(bar.open, bar.high, bar.low, bar.close):
            return None

        avg_vol = statistics.mean(list(volumes)[:-1]) if len(volumes) > 1 else 0.0
        if avg_vol == 0 or bar.volume < 2 * avg_vol:
            return None

        adx = compute_adx(closes_seq, cfg["adx_period"])
        if adx is not None and adx >= cfg["adx_threshold"]:
            return None

        return direction
