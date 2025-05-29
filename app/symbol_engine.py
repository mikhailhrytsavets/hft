import asyncio
import math
import time
from datetime import datetime
from typing import Optional
from collections import deque, defaultdict
import statistics

from app.indicators import CandleAggregator
from src.core.data import OHLCCollector, Bar
from src.core.indicators import compute_adx, compute_adx_info

from pybit.exceptions import InvalidRequestError
from app.config import settings
from app.database import DB
from app.entry_score import compute_entry_score
from app.exchange import BybitClient
from app.market_features import MarketFeatures
from app.notifier import notify_telegram
from app.risk import RiskManager
from src.strategy.entry import BounceEntry
from app.signal_engine import SignalEngine
from app.utils import snap_qty

__all__ = ["SymbolEngine"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _PrecisionCache:
    """Lazy‑loads and caches qtyStep for symbols to avoid repeated REST calls."""

    def __init__(self) -> None:
        self._cache: dict[str, float] = {}

    def step(self, http, symbol: str) -> float:
        if symbol in self._cache:
            return self._cache[symbol]
        try:
            info = http.get_instruments_info(category="linear", symbol=symbol)
            step = float(info["result"]["list"][0]["lotSizeFilter"]["qtyStep"])
        except Exception as exc:  # pragma: no cover – network call
            print(f"[{symbol}] ⚠️ qtyStep fetch failed: {exc}")
            step = 1.0
        self._cache[symbol] = step
        print(f"[{symbol}] ℹ️ qtyStep cached = {step}")
        return step


async def _fetch_closed_pnl(
    client: BybitClient, symbol: str, retries: int = 10
) -> Optional[tuple[float, float]]:
    """Poll Bybit for the most recent closed PnL record."""

    await asyncio.sleep(3)  # allow exchange to register the trade
    for _ in range(retries):
        try:
            resp = client.http.get_closed_pnl(category="linear", symbol=symbol, limit=1)
            rows = resp.get("result", {}).get("list", [])
            if not rows:
                await asyncio.sleep(1)
                continue
            row = rows[0]
            net_pnl = float(row["closedPnl"])
            pnl_pct = net_pnl / float(row["cumEntryValue"]) * 100.0
            return net_pnl, pnl_pct
        except Exception as exc:
            print(f"[{symbol}] ⚠️ closed_pnl fetch error: {exc}")
            await asyncio.sleep(1)
    return None


def _calc_pnl(side: str, entry_price: float, exit_price: float, qty: float) -> float:
    """Return PnL in quote currency for ``qty`` closed at ``exit_price``."""
    if side == "Buy":
        return (exit_price - entry_price) * qty
    return (entry_price - exit_price) * qty




# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class SymbolEngine:
    """Per‑symbol trading engine (market data intake ➜ decisions ➜ order flow)."""

    SPREAD_Z_MAX = 3.0

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        lev = min(settings.trading.leverage, 50)
        self.client = BybitClient(
            symbol=symbol,
            api_key=settings.bybit.api_key,
            api_secret=settings.bybit.api_secret,
            testnet=settings.bybit.testnet,
            demo=settings.bybit.demo,
            channel_type=settings.bybit.channel_type,
            place_orders=settings.bybit.place_orders,
        )
        self.client.set_leverage(self.symbol, lev)

        if settings.trading.enable_hedging:
            try:
                resp = self.client.http.get_positions(
                    category="linear", symbol=self.symbol
                )
                positions = resp.get("result", {}).get("list", [])
                idxs = {p.get("positionIdx") for p in positions}
                hedge = len(positions) > 1 or any(i in (1, 2) for i in idxs)
                if not hedge:
                    print(f"[{self.symbol}] ⚠️ Hedge mode appears disabled")
            except Exception as exc:  # pragma: no cover – network call
                print(f"[{self.symbol}] ⚠️ Hedge mode check failed: {exc}")

        # State / utils -------------------------------------------------------
        self.precision = _PrecisionCache()
        self.signal     = SignalEngine(z_threshold=1.2)
        self.market     = MarketFeatures()
        self.risk       = RiskManager(symbol)
        self.current_sl_price: float | None = None
        self.vol_history = deque(maxlen=50)
        self.volume_window = deque(maxlen=20)
        self.close_window = deque(maxlen=30)
        self.score_history = deque(maxlen=100)
        self.weights = settings.entry_score.symbol_weights.get(
            symbol, settings.entry_score.weights
        )
        self.k = settings.entry_score.symbol_threshold_k.get(
            symbol, settings.entry_score.threshold_k
        )
        self._last_mt_update: float = 0.0
        self._mt_candles: dict[str, list] = defaultdict(list)
        self._candle_agg = CandleAggregator()
        self.ohlc = OHLCCollector()
        self.ohlc.subscribe(self._on_bar)

        # Streaming‑derived fields
        self.latest_obi: float | None = None
        self.latest_spread_z: float | None = None
        self.latest_vbd: float = 0.0
        self.latest_tflow: float = 0.0
        self.latest_vol: float = 0.0

        # Active exchange order ids
        self.sl_order_id: Optional[str] = None
        self.tp_order_id: Optional[str] = None
        # Unique orderLinkId for stop-loss orders will be generated per order
        # to avoid Bybit's "duplicate" error on reused IDs
        self.sl_link_id = f"{symbol}-sl"

        # Streaming will be attached by SymbolEngineManager
        self.manager = None  # set by SymbolEngineManager

        # Restore running state (open position / TP) -----------------------
        self._restore_position()
        self._purge_stale_orders()
        self.risk.reset_trade()
        self.hedge_cycle_count = 0

        # stop flag when daily limit hit
        self._stopped = False

    # ---------------------------------------------------------------------
    # WebSocket handlers
    # ---------------------------------------------------------------------
    def _on_orderbook(self, data) -> None:
        bids, asks = data.get("b", []), data.get("a", [])
        if not (bids and asks):
            return
        self.latest_obi = self.market.compute_obi(bids, asks)
        best_bid, best_ask = float(bids[0][0]), float(asks[0][0])
        self.latest_spread_z = self.market.update_spread(best_bid, best_ask)
        self.risk.latest_spread_z = self.latest_spread_z

    def _on_trades(self, data) -> None:
        buys = sum(float(t["v"]) for t in data if t["S"] == "Buy")
        sells = sum(float(t["v"]) for t in data if t["S"] == "Sell")
        self.latest_vbd    = self.market.update_vbd(buys, sells)
        self.risk.latest_vbd    = self.latest_vbd
        self.latest_tflow  = self.market.update_taker_flow(buys, sells)
        for t in data:
            ts = int((t.get("T") or t.get("ts") or t.get("t"))/1000)
            self.ohlc.on_trade(float(t["p"]), float(t["v"]), ts)

    # ---------------------------------------------------------------------
    # Setup helpers
    # ---------------------------------------------------------------------
    def _restore_position(self) -> None:
        """Populate self.risk.position if Bybit shows an active position."""
        try:
            pos = self.client.http.get_positions(category="linear", symbol=self.symbol)["result"]["list"][0]
            size = float(pos["size"])
            if size:
                self.risk.position.side       = pos["side"]
                self.risk.position.qty        = size
                self.risk.position.avg_price  = float(pos["avgPrice"])
                self.risk.position.open_time  = datetime.utcnow()
                print(f"[{self.symbol}] 🧠 Restored active position {size} {pos['side']} @ {pos['avgPrice']}")
        except Exception as exc:
            print(f"[{self.symbol}] ⚠️ Position restore failed: {exc}")

    def _purge_stale_orders(self) -> None:
        """Keep only *one* valid reduce‑only TP Limit order (if any) and cancel others."""
        try:
            orders = self.client.http.get_open_orders(category="linear", symbol=self.symbol)["result"]["list"]
        except Exception as exc:
            print(f"[{self.symbol}] ⚠️ open_orders fetch failed: {exc}")
            return

        for o in orders:
            keep_tp = (
                o.get("reduceOnly") and o["orderType"] == "Limit" and
                o["side"] == ("Sell" if self.risk.position.side == "Buy" else "Buy")
            )
            if keep_tp and not self.tp_order_id:
                self.tp_order_id = o["orderId"]  # keep the first found
                print(f"[{self.symbol}] 🧠 Keeping existing TP order = {self.tp_order_id}")
                continue
            # otherwise cancel
            try:
                self.client.http.cancel_order(category="linear", symbol=self.symbol, orderId=o["orderId"])
                print(f"[{self.symbol}] 🧹 Canceled stale order {o['orderId']}")
            except Exception as exc:
                print(f"[{self.symbol}] ⚠️ cancel_order failed: {exc}")

    async def _on_bar(self, bar: Bar) -> None:
        await self.market.on_bar(bar)
        self.close_window.append(bar.close)
        self.volume_window.append(bar.volume)

    async def _update_multi_tf(self) -> None:
        """Fetch candles for additional timeframes periodically."""
        mt = settings.multi_tf
        now = time.time()
        if not mt.enable or now - self._last_mt_update < mt.update_seconds:
            return
        for tf in mt.intervals:
            try:
                self._mt_candles[tf] = await self.client.get_klines(
                    self.symbol, tf, limit=mt.trend_confirm_bars
                )
            except Exception as exc:
                print(f"[{self.symbol}] ⚠️ multi_tf fetch {tf}: {exc}")
        self._last_mt_update = now

    # ---------------------------------------------------------------------
    # Quant helpers
    # ---------------------------------------------------------------------
    def _soft_sl_price(self, entry: float, side: str) -> float:
        pct = settings.trading.soft_sl_percent / 100.0
        return entry * (1 + pct) if side == "Buy" else entry * (1 - pct)

    async def safe_qty_calc(self, price: float, risk_percent: float) -> float:
        """Рассчитывает объём позиции, округляя по qtyStep и ограничивает по risk-limit."""
        try:
            if price <= 0:
                raise ValueError("Цена ≤ 0")

            bal_task = asyncio.create_task(
                self.client.get_wallet_balance(accountType="UNIFIED")
            )
            pos_task = asyncio.create_task(self.client.get_position())
            risk_task = asyncio.create_task(
                self.client.max_position_size(price, settings.trading.leverage)
            )
            info, current_pos, max_size = await asyncio.gather(
                bal_task, pos_task, risk_task
            )
            coins = info["result"]["list"][0]["coin"]
            usdt = next((c for c in coins if c["coin"] == "USDT"), None)
            if not usdt:
                raise ValueError("USDT не найден")

            available = float(usdt.get("availableToTrade") or usdt.get("walletBalance") or 0)
            if available <= 0:
                raise ValueError(f"Недостаточный equity: {available}")

            notional = available * (risk_percent / 100) * settings.trading.leverage
            qty_raw = notional / price

            current_qty = float(current_pos.get("size", 0))
            equity = float(usdt.get("walletBalance") or 0)
            if settings.trading.enable_risk_cap:
                max_notional = equity * settings.trading.max_position_risk_percent / 100 * settings.trading.leverage
                curr_notional = current_qty * price
                if curr_notional >= max_notional:
                    raise ValueError(f"Risk cap reached: {curr_notional}/{max_notional}")
                if curr_notional + qty_raw * price > max_notional:
                    qty_raw = (max_notional - curr_notional) / price

            # Ограничение по risk-limit
            allowed = None
            try:
                if max_size:
                    current_size = float(current_pos.get("size", 0))
                    allowed = max_size - current_size
                    if allowed <= 0:
                        raise ValueError(f"Risk-limit reached: {current_size}/{max_size}")
                    if qty_raw > allowed:
                        print(f"[{self.symbol}] ⚠️ Qty {qty_raw} > allowed {allowed}. Обрезаем до allowed")
                        qty_raw = allowed
            except Exception as e:
                print(f"[{self.symbol}] ⚠️ Не смог получить risk-limit: {e}")

            step = self.precision.step(self.client.http, self.symbol)
            qty = snap_qty(qty_raw, step)

            if qty <= 0:
                raise ValueError(f"Qty недопустим: {qty}")

            print(
                f"[{self.symbol}] ✅ Equity={available:.2f}, Risk%={risk_percent:.3f}, "
                f"Notional={notional:.2f}, Qty={qty} (max_size={max_size if max_size is not None else 'N/A'}, allowed={allowed if allowed is not None else 'N/A'})"
            )
            return qty
        except Exception as e:
            print(f"[{self.symbol}] ❌ safe_qty_calc: {type(e).__name__} → {e}")
            raise

    # ---------------------------------------------------------------------
    # Main loop
    # ---------------------------------------------------------------------
    async def run(self) -> None:
        print(f"[{self.symbol}] ⏳ Waiting for first order‑book snapshot…")
        while self.latest_obi is None:
            await asyncio.sleep(0.05)
        print(f"[{self.symbol}] ✅ Market data online – starting price stream")

        warmup_target = max(settings.trading.rsi_period, settings.trading.adx_period * 2) + 1
        warmup_done = len(self.risk.price_window) >= warmup_target
        if not warmup_done:
            print(
                f"[{self.symbol}] 🔄 Warming up indicators "
                f"{len(self.risk.price_window)}/{warmup_target}"
            )

        async for price in self.client.price_stream():
            if self._stopped:
                print(f"[{self.symbol}] 🛑 Engine stopped due to risk limit")
                break
            # ---------------- Feature update -----------------------------
            self.signal.update(price, volume=1.0)
            z        = self.signal.features.zscore()
            spread_z = self.latest_spread_z or 0.0
            vol      = self.market.update_volatility(price)
            self.latest_vol = vol
            self.vol_history.append(vol)
            candle = self._candle_agg.add_tick(price, time.time())
            if candle:
                high, low, close = candle
                self.risk.price_window.append((high, low, close))
                if not warmup_done:
                    print(
                        f"[{self.symbol}] 🔄 Warming up indicators "
                        f"{len(self.risk.price_window)}/{warmup_target}"
                    )
                    if len(self.risk.price_window) >= warmup_target:
                        warmup_done = True
                        print(f"[{self.symbol}] ✅ Indicators ready")
            if not warmup_done:
                continue

            adx, plus_di, minus_di = self.risk._compute_adx_info(settings.trading.adx_period)
            score    = compute_entry_score(
                z,
                self.latest_obi or 0.0,
                self.latest_vbd,
                spread_z,
                self.latest_tflow,
                vol,
                self.weights,
            )
            await self._update_multi_tf()
            mt_score = 0.0
            tf_trend: dict[str, str] = {}
            if settings.multi_tf.enable:
                for tf in settings.multi_tf.intervals:
                    candles = self._mt_candles.get(tf, [])
                    if len(candles) >= settings.multi_tf.trend_confirm_bars:
                        up = all(float(c.get("close") or c.get("c")) > float(c.get("open") or c.get("o")) for c in candles)
                        dn = all(float(c.get("close") or c.get("c")) < float(c.get("open") or c.get("o")) for c in candles)
                        tf_trend[tf] = "UP" if up else "DOWN" if dn else "MIXED"
                        wt = settings.multi_tf.weights.get(tf, 0.0)
                        if up:
                            mt_score += wt
                        elif dn:
                            mt_score -= wt
                    else:
                        tf_trend[tf] = "MIXED"
            score += mt_score
            self.score_history.append(score)
            sigma = statistics.stdev(self.score_history) if len(self.score_history) > 5 else self.latest_vol
            thr   = self.k * sigma
            direction  = (
                "LONG"  if score < -thr else
                "SHORT" if score > thr else None
            )
            print(f"[{self.symbol}] score={score:.2f} → {direction}")

            current_bar = self.ohlc.last_bar
            sig = None
            if current_bar:
                sig = BounceEntry.check(current_bar, self.volume_window, self.close_window, settings.symbol_params.get(self.symbol, {}))
            if sig and self.risk.position.qty == 0:
                if self.manager:
                    await self.manager._maybe_open_position(self, sig.value, price)
                else:
                    await self._open_position(sig.value, price)
                continue

            mode = "range"
            trend_dir = None
            if settings.trading.enable_trend_mode and adx is not None:
                if adx >= settings.trading.trend_adx_threshold:
                    mode = "trend"
                    if plus_di is not None and minus_di is not None:
                        trend_dir = "LONG" if plus_di >= minus_di else "SHORT"
                    else:
                        avg = statistics.mean(self.market.price_window) if self.market.price_window else price
                        trend_dir = "LONG" if price >= avg else "SHORT"
                print(f"[{self.symbol}] Mode={mode}, ADX={adx:.2f}, dir={trend_dir}")

            # ---------------- Entry -------------------------------------
            if direction and self.risk.position.qty == 0:
                if settings.trading.enable_trend_mode and mode == "trend":
                    if trend_dir and direction != trend_dir:
                        print(f"[{self.symbol}] 🚫 TrendMode filter")
                        continue
                if self._entry_filters_fail(spread_z, direction):
                    continue
                if settings.multi_tf.enable:
                    ok = True
                    for tf in settings.multi_tf.intervals:
                        trend = tf_trend.get(tf)
                        if trend is None or trend == "MIXED":
                            ok = False
                            break
                        if direction == "LONG" and trend != "UP":
                            ok = False
                        if direction == "SHORT" and trend != "DOWN":
                            ok = False
                    if not ok:
                        print(f"[{self.symbol}] 🚫 multi-TF filter")
                        continue
                if settings.trading.use_htf_filter:
                    htf = self._higher_tf_trend()
                    if htf == "UP" and direction == "SHORT":
                        print(f"[{self.symbol}] 🚫 HTF filter")
                        continue
                    if htf == "DOWN" and direction == "LONG":
                        print(f"[{self.symbol}] 🚫 HTF filter")
                        continue
                if self.manager:
                    await self.manager._maybe_open_position(self, direction, price)
                else:
                    await self._open_position(direction, price)
                continue  # wait next tick

            # ---------------- Exit / DCA --------------------------------
            await self._manage_position(price)

    # ------------------------------------------------------------------
    # Entry helpers
    # ------------------------------------------------------------------
    def _entry_filters_fail(self, spread_z: float, direction: str) -> bool:
        if settings.trading.enable_time_filter:
            now = datetime.utcnow().hour
            if not (
                settings.trading.trade_start_hour
                <= now
                < settings.trading.trade_end_hour
            ):
                print(f"[{self.symbol}] 🚫 Time filter")
                return True
        if self.vol_history:
            avg_vol = statistics.mean(self.vol_history)
            thr_vol = avg_vol * 3
            if self.latest_vol > thr_vol:
                print(f"[{self.symbol}] 🚫 Volatility filter")
                return True
        if abs(spread_z) > self.SPREAD_Z_MAX:
            print(f"[{self.symbol}] 🚫 Spread‑Z filter")
            return True
        if settings.trading.enable_rsi_filter:
            prices = list(self.market.price_window)
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
                    print(f"[{self.symbol}] 🚫 RSI filter")
                    return True
                if direction == "SHORT" and rsi <= settings.trading.rsi_oversold:
                    print(f"[{self.symbol}] 🚫 RSI filter")
                    return True
        if settings.trading.use_adx_filter:
            prices = list(self.market.price_window)
            adx = compute_adx(prices, settings.trading.adx_period)
            if adx is not None and adx >= settings.trading.adx_threshold:
                print(f"[{self.symbol}] 🚫 ADX filter")
                return True
        return False

    def _higher_tf_trend(self) -> str | None:
        """Return trend of the latest higher timeframe candle."""
        try:
            resp = self.client.http.get_kline(
                category="linear",
                symbol=self.symbol,
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
        except Exception as exc:
            print(f"[{self.symbol}] ⚠️ HTF fetch error: {exc}")
        return None

    async def _open_position(self, direction: str, price: float) -> None:
        side = "Buy" if direction == "LONG" else "Sell"
        try:
            if (
                settings.risk.max_open_positions
                and len(RiskManager.active_positions) >= settings.risk.max_open_positions
            ):
                print(f"[{self.symbol}] 🚫 Max open positions reached")
                return
            # current equity check -----------------------------------------
            info = await self.client.get_wallet_balance(accountType="UNIFIED")
            coins = info["result"]["list"][0]["coin"]
            usdt  = next((c for c in coins if c["coin"] == "USDT"), None)
            equity = float(usdt.get("walletBalance") or 0) if usdt else 0.0
            allowed = await self.risk.check_equity(equity)
            if not allowed:
                self._stopped = True
                return

            qty = await self.safe_qty_calc(price, settings.trading.initial_risk_percent)
            volume = qty * price
            total_vol = sum(RiskManager.position_volumes.values())
            if (
                settings.risk.max_total_volume
                and total_vol + volume > settings.risk.max_total_volume
            ):
                print(f"[{self.symbol}] 🚫 Total volume limit reached")
                return
        except Exception as exc:
            print(f"[{self.symbol}] Qty calc failed: {exc}")
            return
        await self.client.create_limit_order(side, qty, price)
        await notify_telegram(f"📥 Entry {self.symbol} {side} qty={qty}")

        RiskManager.active_positions.add(self.symbol)
        RiskManager.position_volumes[self.symbol] = volume

        self.risk.position.side = side
        self.risk.position.qty  = qty
        self.risk.position.avg_price = price
        self.risk.position.open_time = datetime.utcnow()
        self.risk.reset_trade()

        # initial SL ------------------------------------------------------
        sl_price = self._soft_sl_price(price, side)
        await self._set_sl(qty, sl_price)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------
    async def _manage_position(self, price: float) -> None:
        signal = await self.risk.check_exit(price)
        if not signal:
            if self.risk.tp1_done and self.risk.trail_price and self.current_sl_price is not None:
                if (
                    self.risk.position.side == "Buy" and self.risk.trail_price > self.current_sl_price
                ) or (
                    self.risk.position.side == "Sell" and self.risk.trail_price < self.current_sl_price
                ):
                    await self._set_sl(self.risk.position.qty, self.risk.trail_price)
            return
        if signal == "DCA":
            await self._handle_dca(price)
        elif signal == "TP2":
            await self._handle_tp2(price)
        elif signal == "TP1":
            await self._handle_tp1(price)
        else:  # TP, SOFT_SL, TRAIL or TIMEOUT
            if signal in ("SOFT_SL", "TRAIL") and settings.trading.enable_hedging:
                await self._maybe_hedge(self.risk.position.side, self.risk.position.qty, price, datetime.utcnow())
                return
            await self._close_position(signal, price)

    async def _maybe_hedge(self, side: str, qty: float, price: float, now: datetime):
        stg = settings.trading

        if self.hedge_cycle_count >= stg.max_hedges:
            await self._close_position("SOFT_SL", price)
            return

        if stg.hedge_delay_seconds > 0:
            await asyncio.sleep(stg.hedge_delay_seconds)

        if stg.enable_hedge_adx_filter:
            closes = [c for _, _, c in self.risk.price_window]
            adx = compute_adx(closes, settings.trading.adx_period)
            if adx is None or adx < stg.hedge_adx_threshold:
                await self._close_position("SOFT_SL", price)
                return

        step = self.precision.step(self.client.http, self.symbol)
        hedge_qty = snap_qty(qty * stg.hedge_size_ratio, step)
        if hedge_qty <= 0:
            await self._close_position("SOFT_SL", price)
            return

        side_flip = "Sell" if side == "Buy" else "Buy"
        await self._close_position("SOFT_SL", price)
        try:
            await self.client.create_limit_order(side_flip, hedge_qty, price)
        except Exception as exc:
            print(f"[{self.symbol}] Hedge failed: {exc}")
            return

        self.hedge_cycle_count += 1
        RiskManager.active_positions.add(self.symbol)
        RiskManager.position_volumes[self.symbol] = hedge_qty * price
        self.risk.reset_trade()
        self.risk.position.side = side_flip
        self.risk.position.qty = hedge_qty
        self.risk.position.avg_price = price
        self.risk.position.open_time = now

        sl_px = self._soft_sl_price(price, side_flip)
        await self._set_sl(hedge_qty, sl_px)

    async def _handle_dca(self, price: float) -> None:
        base = settings.trading.initial_risk_percent
        q = settings.trading.dca_risk_multiplier
        risk_pct = base * (q ** self.risk.dca_levels)
        if settings.trading.enable_risk_cap:
            used = sum(base * (q ** i) for i in range(self.risk.dca_levels))
            remaining = settings.trading.max_position_risk_percent - used
            if remaining <= 0:
                print(f"[{self.symbol}] DCA risk cap reached")
                return
            risk_pct = min(risk_pct, remaining)
        try:
            qty = await self.safe_qty_calc(price, risk_pct)
        except Exception as exc:
            print(f"[{self.symbol}] DCA qty calc failed: {exc}")
            return
        await self.client.create_limit_order(self.risk.position.side, qty, price)
        RiskManager.position_volumes[self.symbol] = (
            RiskManager.position_volumes.get(self.symbol, 0.0) + qty * price
        )

        total_qty = self.risk.position.qty + qty
        new_avg   = (self.risk.position.avg_price * self.risk.position.qty + price * qty) / total_qty
        self.risk.position.qty = total_qty
        self.risk.position.avg_price = new_avg
        self.risk.initial_qty = total_qty
        self.risk.entry_value += qty * price
        self.risk.last_dca_price = price
        await notify_telegram(f"➕ DCA {self.symbol}: +{qty} → avg {new_avg:.4f}")

        # move SL --------------------------------------------------------
        sl_px = self._soft_sl_price(new_avg, self.risk.position.side)
        await self._set_sl(total_qty, sl_px)

    async def _handle_tp1(self, price: float) -> None:
        step = self.precision.step(self.client.http, self.symbol)
        close_qty = snap_qty(
            self.risk.position.qty * settings.trading.tp1_close_ratio, step
        )
        if close_qty > 0:
            side_close = "Sell" if self.risk.position.side == "Buy" else "Buy"
            try:
                await self.client.create_limit_order(
                    side_close,
                    close_qty,
                    price,
                    reduce_only=True,
                )
            except Exception as exc:
                print(f"[{self.symbol}] TP1 close failed: {exc}")
                return
            self.risk.position.qty -= close_qty
            pnl_part = _calc_pnl(self.risk.position.side, self.risk.position.avg_price, price, close_qty)
            self.risk.realized_pnl += pnl_part
            await notify_telegram(f"💰 TP1 {self.symbol}: {close_qty} closed")
            total_pct = (
                self.risk.realized_pnl / self.risk.entry_value * 100
                if self.risk.entry_value else 0.0
            )
            net_usdt = self.risk.realized_pnl
            emoji = "🟢" if net_usdt > 0 else "🔴"
            sign  = "+" if net_usdt > 0 else ""
            msg = (
                f"{emoji} <b>TP1 {self.symbol}</b>\n"
                f"💰 PnL: <b>{sign}{net_usdt:.2f} USDT</b> ({sign}{total_pct:.2f}%)\n"
            )
            await notify_telegram(msg)
        # move SL to breakeven with a small profit buffer
        be = settings.trading.min_profit_to_be
        if be:
            if self.risk.position.side == "Buy":
                sl_px = self.risk.position.avg_price * (1 + be / 100)
            else:
                sl_px = self.risk.position.avg_price * (1 - be / 100)
        else:
            sl_px = self.risk.position.avg_price
        await self._set_sl(self.risk.position.qty, sl_px)

    async def _handle_tp2(self, price: float) -> None:
        if settings.trading.tp2_close_ratio is None:
            return
        step = self.precision.step(self.client.http, self.symbol)
        close_qty = snap_qty(
            self.risk.position.qty * settings.trading.tp2_close_ratio, step
        )
        if close_qty <= 0:
            return
        side_close = "Sell" if self.risk.position.side == "Buy" else "Buy"
        try:
            await self.client.create_limit_order(
                side_close,
                close_qty,
                price,
                reduce_only=True,
            )
        except Exception as exc:
            print(f"[{self.symbol}] TP2 close failed: {exc}")
            return
        self.risk.position.qty -= close_qty
        pnl_part = _calc_pnl(self.risk.position.side, self.risk.position.avg_price, price, close_qty)
        self.risk.realized_pnl += pnl_part
        await notify_telegram(f"💰 TP2 {self.symbol}: {close_qty} closed")
        total_pct = (
            self.risk.realized_pnl / self.risk.entry_value * 100
            if self.risk.entry_value else 0.0
        )
        net_usdt = self.risk.realized_pnl
        emoji = "🟢" if net_usdt > 0 else "🔴"
        sign = "+" if net_usdt > 0 else ""
        msg = (
            f"{emoji} <b>TP2 {self.symbol}</b>\n"
            f"💰 PnL: <b>{sign}{net_usdt:.2f} USDT</b> ({sign}{total_pct:.2f}%)\n"
        )
        await notify_telegram(msg)

    async def _close_position(self, exit_signal: str, mkt_price: float) -> None:
        side_close = "Sell" if self.risk.position.side == "Buy" else "Buy"
        step       = self.precision.step(self.client.http, self.symbol)
        qty_close  = snap_qty(self.risk.position.qty, step)
        if qty_close <= 0:
            return
        try:
            await self.client.create_limit_order(
                side_close,
                qty_close,
                mkt_price,
                reduce_only=True,
            )
        except InvalidRequestError as exc:
            if "110017" in str(exc):
                print(f"[{self.symbol}] ℹ️ Close order rejected: {exc}")
            else:
                print(f"[{self.symbol}] ⚠️ close_order failed: {exc}")
                return
        pnl_part = _calc_pnl(self.risk.position.side, self.risk.position.avg_price, mkt_price, qty_close)
        self.risk.realized_pnl += pnl_part
        total_pct = (
            self.risk.realized_pnl / self.risk.entry_value * 100
            if self.risk.entry_value else 0.0
        )
        net_usdt = self.risk.realized_pnl
        emoji = "🟢" if net_usdt > 0 else "🔴"
        sign  = "+" if net_usdt > 0 else ""
        msg = (
            f"{emoji} <b>{exit_signal} {self.symbol}</b>\n"
            f"💰 PnL: <b>{sign}{net_usdt:.2f} USDT</b> ({sign}{total_pct:.2f}%)\n"
        )
        await notify_telegram(msg)
        async with DB() as db:
            await db.log(side_close, qty_close, mkt_price, self.risk.position.avg_price, net_usdt)
        self.risk.position.reset()
        self.risk.reset_trade()
        RiskManager.active_positions.discard(self.symbol)
        RiskManager.position_volumes.pop(self.symbol, None)
        await self._cancel_all_active_orders()
        self.sl_order_id = None
        self.tp_order_id = None
        self.current_sl_price = None
        if self.manager:
            self.manager.position_closed(self)

    async def _set_sl(self, qty: float, sl_price: float) -> None:
        """Record stop price without placing orders on the exchange."""
        step = self.precision.step(self.client.http, self.symbol)
        qty_r = snap_qty(qty, step)

        current = self.close_window[-1] if self.close_window else None
        if current is not None:
            if self.risk.position.side == "Buy" and sl_price >= current:
                sl_price = current * 0.999
            elif self.risk.position.side == "Sell" and sl_price <= current:
                sl_price = current * 1.001

        self.current_sl_price = sl_price
        self.sl_order_id = None

    async def _cancel_all_active_orders(self):
        try:
            orders_resp = await self.client.get_open_orders(category="linear", symbol=self.symbol)
            orders = orders_resp["result"]["list"]
            for o in orders:
                try:
                    await self.client.cancel_order(category="linear", symbol=self.symbol, orderId=o["orderId"])
                except Exception:
                    pass
        except Exception:
            pass

