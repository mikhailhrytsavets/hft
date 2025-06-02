from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Tuple

from app.config import settings

if TYPE_CHECKING:
    from .risk import RiskManager


async def check_exit(risk: 'RiskManager', price: float) -> Tuple[str | None, str | None]:
    """Return exit signal and reason for given price."""
    if risk.position.qty == 0:
        return None, None

    change = risk.percent(price, risk.position.avg_price)
    stg = settings.trading

    # Hard stop-loss
    if stg.hard_sl_percent:
        limit = stg.hard_sl_percent
        if ((risk.position.side == "Buy" and change <= -limit) or
                (risk.position.side == "Sell" and change >= limit)):
            reason = f"HARD_SL: price change {change:.2f}% exceeds limit {limit}%"
            return "HARD_SL", reason

    # ATR-based stop
    period = settings.symbol_params.get(risk.symbol, settings.SymbolParams()).atr_period
    if stg.use_atr_stop and len(risk.price_window) >= period + 1:
        atr_v = risk._compute_atr(period)
        if atr_v:
            threshold = stg.atr_stop_multiplier * atr_v
            if ((risk.position.side == "Buy" and price <= risk.position.avg_price - threshold) or
                    (risk.position.side == "Sell" and price >= risk.position.avg_price + threshold)):
                reason = f"SOFT_SL: ATR stop, move {abs(change):.2f}% >= {threshold:.2f}"
                return "SOFT_SL", reason

    # Break-even by profit percent
    if stg.break_even_after_percent and not risk.tp1_done:
        be = stg.break_even_after_percent
        hit_be = ((risk.position.side == "Buy" and change >= be) or
                   (risk.position.side == "Sell" and change <= -be))
        if hit_be:
            risk.tp1_done = True
            risk.trail_price = risk.position.avg_price
            risk.best_price = price

    # Break-even by time
    if (stg.break_even_after_minutes > 0 and not risk.tp1_done and
            datetime.utcnow() - risk.position.open_time >= timedelta(minutes=stg.break_even_after_minutes)):
        minp = stg.min_profit_to_be
        if ((risk.position.side == "Buy" and change >= minp) or
                (risk.position.side == "Sell" and change <= -minp)):
            risk.tp1_done = True
            risk.trail_price = risk.position.avg_price
            risk.best_price = price

    # Position timeout
    if (stg.enable_position_timeout and stg.max_position_minutes > 0 and
            datetime.utcnow() - risk.position.open_time > timedelta(minutes=stg.max_position_minutes)):
        minutes = (datetime.utcnow() - risk.position.open_time).total_seconds() / 60
        reason = f"TIMEOUT: position held {minutes:.1f}m > {stg.max_position_minutes}m"
        return "TIMEOUT", reason

    # Fallback TP when partial TPs disabled
    if stg.tp1_percent is None and stg.tp2_percent is None:
        tp_pct = abs(stg.take_profit_percent)
        if ((risk.position.side == "Buy" and change >= tp_pct) or
                (risk.position.side == "Sell" and change <= -tp_pct)):
            reason = f"TP: fallback take profit {abs(change):.2f}% >= {tp_pct}%"
            return "TP", reason

    # TP1
    if not risk.tp1_done:
        tp1_pct = abs(stg.tp1_percent) if stg.tp1_percent is not None else None
        if tp1_pct is not None:
            if ((risk.position.side == "Buy" and change >= tp1_pct) or
                    (risk.position.side == "Sell" and change <= -tp1_pct)):
                risk.tp1_done = True
                risk.best_price = price
                offset = stg.trailing_distance_percent / 100
                trail = price * (1 - offset) if risk.position.side == "Buy" else price * (1 + offset)
                if risk.position.side == "Buy":
                    risk.trail_price = max(trail, risk.position.avg_price)
                else:
                    risk.trail_price = min(trail, risk.position.avg_price)
                reason = f"TP1 hit at change {change:.2f}%"
                return "TP1", reason

    # TP2
    if risk.tp1_done and not risk.tp2_done and stg.tp2_percent is not None:
        tp2_pct = abs(stg.tp2_percent)
        if ((risk.position.side == "Buy" and change >= tp2_pct) or
                (risk.position.side == "Sell" and change <= -tp2_pct)):
            risk.tp2_done = True
            risk.best_price = price
            reason = f"TP2 hit at change {change:.2f}%"
            return "TP2", reason

    # Trailing stop
    if risk.tp1_done and (stg.tp2_percent is None or risk.tp2_done):
        offset = stg.trailing_distance_percent / 100
        if risk.position.side == "Buy":
            risk.best_price = max(risk.best_price or price, price)
            new_trail = risk.best_price * (1 - offset)
            if risk.trail_price is None or new_trail > risk.trail_price:
                risk.trail_price = new_trail
            if risk.trail_price < risk.position.avg_price:
                risk.trail_price = risk.position.avg_price
            if price <= risk.trail_price:
                reason = f"TRAIL stop hit at {price:.4f}"
                return "TRAIL", reason
        else:
            risk.best_price = min(risk.best_price or price, price)
            new_trail = risk.best_price * (1 + offset)
            if risk.trail_price is None or new_trail < risk.trail_price:
                risk.trail_price = new_trail
            if risk.trail_price > risk.position.avg_price:
                risk.trail_price = risk.position.avg_price
            if price >= risk.trail_price:
                reason = f"TRAIL stop hit at {price:.4f}"
                return "TRAIL", reason

    # Final TP
    tp_pct_final = abs(stg.take_profit_percent)
    if ((risk.position.side == "Buy" and change >= tp_pct_final) or
            (risk.position.side == "Sell" and change <= -tp_pct_final)):
        reason = f"TP: change {change:.2f}% >= {tp_pct_final}%"
        return "TP", reason

    # DCA
    if risk._need_dca(price, change, datetime.utcnow()):
        risk.dca_levels += 1
        risk.last_dca_price = price
        risk.last_dca_time = datetime.utcnow()
        base_step = stg.dca_step_percent * (
            risk.dca_levels * (stg.dca_step_multiplier ** (risk.dca_levels - 1))
        )
        direction = "<=" if risk.position.side == "Buy" else ">="
        reason = f"DCA level {risk.dca_levels} triggered: change {change:.2f}% {direction} {base_step:.2f}%"
        return "DCA", reason

    # Soft SL by time
    if stg.soft_sl_minutes > 0:
        if datetime.utcnow() - risk.position.open_time > timedelta(minutes=stg.soft_sl_minutes):
            if ((risk.position.side == "Buy" and change < 0) or
                    (risk.position.side == "Sell" and change > 0)):
                mins = (datetime.utcnow() - risk.position.open_time).total_seconds() / 60
                reason = f"SOFT_SL: time {mins:.1f}m > {stg.soft_sl_minutes}m"
                return "SOFT_SL", reason

    # Soft SL by loss
    sl_pct = abs(stg.soft_sl_percent)
    if ((risk.position.side == "Buy" and change <= -sl_pct) or
            (risk.position.side == "Sell" and change >= sl_pct)):
        reason = f"SOFT_SL: loss {abs(change):.2f}% >= {sl_pct}%"
        return "SOFT_SL", reason

    return None, None
