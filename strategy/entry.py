# Refactored on 2024-06-06 to remove legacy coupling
from __future__ import annotations

from enum import Enum
from typing import Sequence, Tuple
import statistics


class Signal(Enum):
    LONG = 1
    SHORT = -1
    FLAT = 0


def is_reversal_candle(open_p: float, high: float, low: float, close: float) -> bool:
    rng = high - low
    if rng <= 0:
        return False
    body = abs(close - open_p)
    upper = high - max(open_p, close)
    lower = min(open_p, close) - low
    if body <= rng * 0.7 and (upper >= rng * 0.1 or lower >= rng * 0.1):
        return True
    if open_p <= low and close >= open_p + rng * 0.6:
        return True
    if open_p >= high and close <= open_p - rng * 0.6:
        return True
    return False


class BounceEntry:
    @staticmethod
    def generate_signal(
        bar,
        volume_window: Sequence[float],
        bb_params: Tuple[float | None, float | None],
        rsi_params: Tuple[float, float, float],
        adx: float,
    ) -> Signal:
        lower, upper = bb_params
        rsi_val, rsi_low, rsi_high = rsi_params
        if lower is None or upper is None:
            return Signal.FLAT
        direction = Signal.FLAT
        if bar.close <= lower:
            direction = Signal.LONG
        elif bar.close >= upper:
            direction = Signal.SHORT
        else:
            return Signal.FLAT

        if direction == Signal.LONG and rsi_val >= rsi_low:
            return Signal.FLAT
        if direction == Signal.SHORT and rsi_val <= rsi_high:
            return Signal.FLAT

        if adx >= 25:
            return Signal.FLAT

        if not is_reversal_candle(bar.open, bar.high, bar.low, bar.close):
            return Signal.FLAT

        if len(volume_window) < 2:
            return Signal.FLAT
        avg_vol = statistics.mean(volume_window[:-1]) if len(volume_window) > 1 else 0.0
        if avg_vol <= 0 or bar.volume < 2 * avg_vol:
            return Signal.FLAT

        return direction

    @staticmethod
    def check(bar, volume_window: Sequence[float], close_window: Sequence[float], params: object | dict) -> Signal | None:
        dev = getattr(params, "bb_dev", None)
        if isinstance(params, dict):
            dev = params.get("bb_dev", dev)
        bb_dev = dev if dev is not None else 2.0
        if len(close_window) < 20:
            return None
        from app import indicators

        lower, _, upper = indicators.bollinger(list(close_window), 20, bb_dev)
        rsi_v = indicators.rsi(list(close_window), 14)
        sig = BounceEntry.generate_signal(
            bar,
            list(volume_window),
            (lower, upper),
            (rsi_v, 30.0, 70.0),
            0.0,
        )
        return sig if sig is not Signal.FLAT else None
