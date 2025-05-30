# Utility helpers extracted from SymbolEngine for better modularity.

from __future__ import annotations

import asyncio
import statistics
from datetime import datetime

from app.config import settings
from app.utils import snap_qty
from app.risk import RiskManager
from app.notifier import notify_telegram
from legacy.core.indicators import compute_adx


# ---------------------------------------------------------------------------
# Entry helpers
# ---------------------------------------------------------------------------

def entry_filters_fail(engine, spread_z: float, direction: str) -> bool:
    """Return ``True`` if any entry filter blocks opening a position."""
    if settings.trading.enable_time_filter:
        now = datetime.utcnow().hour
        if not (
            settings.trading.trade_start_hour
            <= now
            < settings.trading.trade_end_hour
        ):
            print(f"[{engine.symbol}] 🚫 Time filter")
            return True
    if engine.vol_history:
        avg_vol = statistics.mean(engine.vol_history)
        thr_vol = avg_vol * 3
        if engine.latest_vol > thr_vol:
            print(f"[{engine.symbol}] 🚫 Volatility filter")
            return True
    if abs(spread_z) > engine.SPREAD_Z_MAX:
        print(f"[{engine.symbol}] 🚫 Spread‑Z filter")
        return True
    if settings.trading.enable_rsi_filter:
        prices = list(engine.market.price_window)
        if len(prices) >= settings.trading.rsi_period + 1:
            import numpy as np

            deltas = np.diff(prices)
            ups = np.clip(deltas, 0, None)
            downs = -np.clip(deltas, None, 0)
            avg_gain = np.mean(ups[-settings.trading.rsi_period:])
            avg_loss = np.mean(downs[-settings.trading.rsi_period:])
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            if direction == "LONG" and rsi >= settings.trading.rsi_overbought:
                print(f"[{engine.symbol}] 🚫 RSI filter")
                return True
            if direction == "SHORT" and rsi <= settings.trading.rsi_oversold:
                print(f"[{engine.symbol}] 🚫 RSI filter")
                return True
    if settings.trading.use_adx_filter:
        prices = list(engine.market.price_window)
        adx = compute_adx(prices, settings.trading.adx_period)
        if adx is not None and adx >= settings.trading.adx_threshold:
            print(f"[{engine.symbol}] 🚫 ADX filter")
            return True
    return False


def higher_tf_trend(engine) -> str | None:
    """Return trend of the latest higher timeframe candle."""
    try:
        resp = engine.client.http.get_kline(
            category="linear",
            symbol=engine.symbol,
            interval=settings.trading.htf_interval,
            limit=1,
        )
        candle = resp.get("result", {}).get("list", [])[0]
        open_price = float(candle.get("open") or candle.get("o"))
        close_price = float(candle.get("close") or candle.get("c"))
        if close_price > open_price:
            return "UP"
        if close_price < open_price:
            return "DOWN"
    except Exception as exc:  # pragma: no cover - network call
        print(f"[{engine.symbol}] ⚠️ HTF fetch error: {exc}")
    return None


# ---------------------------------------------------------------------------
# DCA / Hedge helpers
# ---------------------------------------------------------------------------

async def maybe_hedge(
    engine,
    side: str,
    qty: float,
    price: float,
    now: datetime,
    reason: str,
) -> None:
    stg = settings.trading

    if engine.hedge_cycle_count >= stg.max_hedges:
        await engine._close_position(reason, price)
        return

    if stg.hedge_delay_seconds > 0:
        await asyncio.sleep(stg.hedge_delay_seconds)

    if stg.enable_hedge_adx_filter:
        closes = [c for _, _, c in engine.risk.price_window]
        adx = compute_adx(closes, settings.trading.adx_period)
        if adx is None or adx < stg.hedge_adx_threshold:
            await engine._close_position(reason, price)
            return

    step = engine.precision.step(engine.client.http, engine.symbol)
    hedge_qty = snap_qty(qty * stg.hedge_size_ratio, step)
    if hedge_qty <= 0:
        await engine._close_position(reason, price)
        return

    side_flip = "Sell" if side == "Buy" else "Buy"
    await engine._close_position(reason, price)
    try:
        await engine.client.create_market_order(side_flip, hedge_qty)
    except Exception as exc:  # pragma: no cover - network call
        print(f"[{engine.symbol}] Hedge failed: {exc}")
        return
    print(f"[{engine.symbol}] ♻️ Hedge {side_flip} {hedge_qty}")
    await notify_telegram(
        f"♻️ Hedge {engine.symbol}: {side_flip} qty={hedge_qty}"
    )

    engine.hedge_cycle_count += 1
    RiskManager.active_positions.add(engine.symbol)
    RiskManager.position_volumes[engine.symbol] = hedge_qty * price
    engine.risk.reset_trade()
    engine.risk.position.side = side_flip
    engine.risk.position.qty = hedge_qty
    engine.risk.position.avg_price = price
    engine.risk.position.open_time = now

    sl_px = engine._soft_sl_price(price, side_flip)
    await engine._set_sl(hedge_qty, sl_px, price)


async def handle_dca(engine, price: float) -> None:
    base = settings.trading.initial_risk_percent
    q = settings.trading.dca_risk_multiplier
    risk_pct = base * (q ** engine.risk.dca_levels)
    if settings.trading.enable_risk_cap:
        used = sum(base * (q ** i) for i in range(engine.risk.dca_levels))
        remaining = settings.trading.max_position_risk_percent - used
        if remaining <= 0:
            print(f"[{engine.symbol}] DCA risk cap reached")
            return
        risk_pct = min(risk_pct, remaining)
    try:
        qty = await engine.safe_qty_calc(price, risk_pct)
    except Exception as exc:  # pragma: no cover - network call
        print(f"[{engine.symbol}] DCA qty calc failed: {exc}")
        return
    await engine.client.create_market_order(engine.risk.position.side, qty)
    RiskManager.position_volumes[engine.symbol] = (
        RiskManager.position_volumes.get(engine.symbol, 0.0) + qty * price
    )

    total_qty = engine.risk.position.qty + qty
    new_avg = (
        engine.risk.position.avg_price * engine.risk.position.qty + price * qty
    ) / total_qty
    engine.risk.position.qty = total_qty
    engine.risk.position.avg_price = new_avg
    engine.risk.initial_qty = total_qty
    engine.risk.entry_value += qty * price
    engine.risk.last_dca_price = price
    await notify_telegram(f"➕ DCA {engine.symbol}: +{qty} → avg {new_avg:.4f}")

    sl_px = engine._soft_sl_price(new_avg, engine.risk.position.side)
    await engine._set_sl(total_qty, sl_px, price)

