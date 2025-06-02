import asyncio
import time
from datetime import datetime
from typing import Optional
from collections import deque, defaultdict
import statistics

from app.indicators import CandleAggregator
from legacy.core.data import OHLCCollector, Bar

from pybit.exceptions import InvalidRequestError
from app.config import settings
from app.database import DB
from app.entry_score import compute_entry_score
from app.exchange import BybitClient
from app.market_features import MarketFeatures
from app.notifier import notify_telegram
from app.risk import RiskManager
from legacy.strategy.bounce_entry import BounceEntry, EntrySignal
from app.signal_engine import SignalEngine
from app.utils import snap_qty
from app.strategy_utils import (
    entry_filters_fail,
    higher_tf_trend,
    handle_dca,
    maybe_hedge,
)

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


async def _fetch_closed_pnl(self, retries: int = 10) -> Optional[tuple[float, float]]:
    """Return aggregated PnL for trades newer than ``self.last_pnl_id``."""

    await asyncio.sleep(3)  # allow exchange to register the trade
    for _ in range(retries):
        try:
            resp = self.client.http.get_closed_pnl(
                category="linear", symbol=self.symbol, limit=10
            )
            rows = resp.get("result", {}).get("list", [])
            if not rows:
                await asyncio.sleep(1)
                continue

            # rows are newest first
            if self.last_pnl_id is None:
                row = rows[0]
                self.last_pnl_id = row.get("id")
                net_pnl = float(row["closedPnl"])
                pnl_pct = net_pnl / float(row["cumEntryValue"]) * 100.0
                return net_pnl, pnl_pct

            new_rows = []
            for r in rows:
                rid = r.get("id")
                if rid == self.last_pnl_id:
                    break
                new_rows.append(r)

            if not new_rows:
                await asyncio.sleep(1)
                continue

            self.last_pnl_id = new_rows[0].get("id")
            net = sum(float(r["closedPnl"]) for r in new_rows)
            entry = sum(float(r["cumEntryValue"]) for r in new_rows)
            pnl_pct = net / entry * 100.0 if entry else 0.0
            return net, pnl_pct
        except Exception as exc:
            print(f"[{self.symbol}] ⚠️ closed_pnl fetch error: {exc}")
            await asyncio.sleep(1)
    return None




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
        self._candle_agg = CandleAggregator(settings.trading.candle_interval_sec)
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
        self.entry_order_id: Optional[str] = None

        # Streaming will be attached by SymbolEngineManager
        self.manager = None  # set by SymbolEngineManager

        # Restore running state (open position / TP) -----------------------
        self._restore_position()
        self._purge_stale_orders()
        self.risk.reset_trade()
        self.hedge_cycle_count = 0
        self.last_pnl_id: str | None = None

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

        # restore open SL/TP orders
        try:
            orders = self.client.http.get_open_orders(category="linear", symbol=self.symbol)["result"]["list"]
            for o in orders:
                if o.get("reduceOnly"):
                    if o["orderType"] == "Market" and o.get("triggerPrice"):
                        self.sl_order_id = o["orderId"]
                        self.current_sl_price = float(o.get("triggerPrice"))
                    elif o["orderType"] == "Limit" and o["side"] == ("Sell" if self.risk.position.side == "Buy" else "Buy"):
                        if not self.tp_order_id:
                            self.tp_order_id = o["orderId"]
        except Exception as exc:
            print(f"[{self.symbol}] ⚠️ Order restore failed: {exc}")

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
            features = (
                f"z={z:.2f}, obi={self.latest_obi or 0.0:.2f}, "
                f"vbd={self.latest_vbd:.2f}, spread={spread_z:.2f}, "
                f"volatility={vol:.5f}"
            )
            self.latest_vol = vol
            self.vol_history.append(vol)
            print(f"[{self.symbol}] vol={self.latest_vol:.5f}")
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
                sig = BounceEntry.check(
                    current_bar,
                    self.volume_window,
                    self.close_window,
                    settings.symbol_params.get(self.symbol, {}),
                )

            if sig and self.risk.position.qty == 0:
                if settings.multi_tf.enable:
                    ok = True
                    for tf in settings.multi_tf.intervals:
                        trend = tf_trend.get(tf)
                        if trend is None or trend == "MIXED":
                            ok = False
                            break
                        if sig is EntrySignal.LONG and trend != "UP":
                            ok = False
                            break
                        if sig is EntrySignal.SHORT and trend != "DOWN":
                            ok = False
                            break
                    if not ok:
                        print(f"[{self.symbol}] 🚫 multi-TF filter (bounce)")
                        sig = None
                if sig:
                    reason = f"Bounce {sig.value}"
                    if self.manager:
                        await self.manager._maybe_open_position(
                            self,
                            sig.value,
                            price,
                            reason,
                            "none",
                            features,
                        )
                    else:
                        await self._open_position(
                            sig.value,
                            price,
                            reason,
                            "none",
                            features,
                        )
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
                if entry_filters_fail(self, spread_z, direction):
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
                    htf = higher_tf_trend(self)
                    if htf == "UP" and direction == "SHORT":
                        print(f"[{self.symbol}] 🚫 HTF filter")
                        continue
                    if htf == "DOWN" and direction == "LONG":
                        print(f"[{self.symbol}] 🚫 HTF filter")
                        continue
                reason = f"score={score:.2f} > thr" if direction == "SHORT" else f"score={score:.2f} < -thr"
                if self.manager:
                    await self.manager._maybe_open_position(
                        self,
                        direction,
                        price,
                        reason,
                        "none",
                        features,
                    )
                else:
                    await self._open_position(
                        direction,
                        price,
                        reason,
                        "none",
                        features,
                    )
                continue  # wait next tick

            # ---------------- Exit / DCA --------------------------------
            await self._manage_position(price)

    # ------------------------------------------------------------------
    # Entry helpers
    # ------------------------------------------------------------------

    async def _open_position(
        self,
        direction: str,
        price: float,
        reason: str | None = None,
        filters: str | None = None,
        features: str | None = None,
    ) -> None:
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
        resp = await self.client.create_market_order(side, qty)
        order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None
        if order_id:
            self.entry_order_id = order_id
            await self._wait_order_fill(order_id)
            self.entry_order_id = None
        log_msg = (
            f"📥 Entry {self.symbol} {direction.capitalize()} qty={qty:.2f}\n"
            f"📊 Reason: {reason or 'n/a'}\n"
            f"✅ Filters passed: {filters or 'none'}"
        )
        if features:
            log_msg += f"\n📈 Features: {features}"
        print(f"[{self.symbol}] {log_msg}")
        await notify_telegram(log_msg)

        RiskManager.active_positions.add(self.symbol)
        RiskManager.position_volumes[self.symbol] = volume

        self.risk.position.side = side
        self.risk.position.qty = qty
        self.risk.position.avg_price = price
        self.risk.position.open_time = datetime.utcnow()
        self.risk.reset_trade()

        # initial SL ------------------------------------------------------
        sl_price = self._soft_sl_price(price, side)
        await self._set_sl(qty, sl_price, price)

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------
    async def _manage_position(self, price: float) -> None:
        signal, reason = await self.risk.check_exit(price)
        if not signal:
            if self.risk.tp1_done and self.risk.trail_price and self.current_sl_price is not None:
                if (
                    self.risk.position.side == "Buy" and self.risk.trail_price > self.current_sl_price
                ) or (
                    self.risk.position.side == "Sell" and self.risk.trail_price < self.current_sl_price
                ):
                    await self._set_sl(
                        self.risk.position.qty,
                        self.risk.trail_price,
                        price,
                    )
            return
        if signal == "DCA":
            print(f"[{self.symbol}] Exit signal DCA: {reason}")
            await handle_dca(self, price, reason)
        elif signal == "TP2":
            print(f"[{self.symbol}] Exit signal TP2: {reason}")
            await self._handle_tp2(price, reason)
        elif signal == "TP1":
            print(f"[{self.symbol}] Exit signal TP1: {reason}")
            await self._handle_tp1(price, reason)
        else:  # TP, SOFT_SL, TRAIL or TIMEOUT
            if signal in ("SOFT_SL", "TRAIL") and settings.trading.enable_hedging:
                await maybe_hedge(
                    self,
                    self.risk.position.side,
                    self.risk.position.qty,
                    price,
                    datetime.utcnow(),
                    signal,
                )
                return
            await self._close_position(signal, price, reason)


    async def _handle_tp1(self, price: float, reason: str | None = None) -> None:
        step = self.precision.step(self.client.http, self.symbol)
        close_qty = snap_qty(
            self.risk.position.qty * settings.trading.tp1_close_ratio, step
        )
        if close_qty > 0:
            side_close = "Sell" if self.risk.position.side == "Buy" else "Buy"
            try:
                resp = await self.client.create_market_order(
                    side_close,
                    close_qty,
                    reduce_only=True,
                )
                order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None
                if order_id:
                    await self._wait_order_fill(order_id)
            except Exception as exc:
                print(f"[{self.symbol}] TP1 close failed: {exc}")
                return
            self.risk.position.qty -= close_qty
            pnl = await _fetch_closed_pnl(self)
            if pnl:
                self.risk.realized_pnl += pnl[0]
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
                f"📉 Reason: {reason or 'n/a'}\n"
                f"💰 PnL: <b>{sign}{net_usdt:.2f} USDT</b> ({sign}{total_pct:.2f}%)\n"
            )
            await notify_telegram(msg)
        # set initial trailing stop after TP1
        dist = getattr(settings.trading, "trailing_distance_percent", 0.2) / 100
        if self.risk.position.side == "Buy":
            sl_px = price * (1 - dist)
        else:
            sl_px = price * (1 + dist)
        await self._set_sl(self.risk.position.qty, sl_px, price)

    async def _handle_tp2(self, price: float, reason: str | None = None) -> None:
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
            resp = await self.client.create_market_order(
                side_close,
                close_qty,
                reduce_only=True,
            )
            order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None
            if order_id:
                await self._wait_order_fill(order_id)
        except Exception as exc:
            print(f"[{self.symbol}] TP2 close failed: {exc}")
            return
        self.risk.position.qty -= close_qty
        pnl = await _fetch_closed_pnl(self)
        if pnl:
            self.risk.realized_pnl += pnl[0]
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
            f"📉 Reason: {reason or 'n/a'}\n"
            f"💰 PnL: <b>{sign}{net_usdt:.2f} USDT</b> ({sign}{total_pct:.2f}%)\n"
        )
        await notify_telegram(msg)

    async def _close_position(self, exit_signal: str, mkt_price: float, reason: str | None = None) -> None:
        side_close = "Sell" if self.risk.position.side == "Buy" else "Buy"
        step       = self.precision.step(self.client.http, self.symbol)
        qty_close  = snap_qty(self.risk.position.qty, step)
        if qty_close <= 0:
            return
        try:
            resp = await self.client.create_market_order(
                side_close,
                qty_close,
                reduce_only=True,
            )
            order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None
            if order_id:
                await self._wait_order_fill(order_id)
        except InvalidRequestError as exc:
            if "110017" in str(exc):
                print(f"[{self.symbol}] ℹ️ Close order rejected: {exc}")
            else:
                print(f"[{self.symbol}] ⚠️ close_order failed: {exc}")
                return
        pnl = await _fetch_closed_pnl(self)
        if pnl:
            self.risk.realized_pnl += pnl[0]
        total_pct = (
            self.risk.realized_pnl / self.risk.entry_value * 100
            if self.risk.entry_value else 0.0
        )
        net_usdt = self.risk.realized_pnl
        emoji = "🟢" if net_usdt > 0 else "🔴"
        sign  = "+" if net_usdt > 0 else ""
        duration = datetime.utcnow() - self.risk.position.open_time
        dur_str = str(duration).split(".")[0]
        msg = (
            f"{emoji} <b>{exit_signal} {self.symbol}</b>\n"
            f"📉 Reason: {reason or 'n/a'}\n"
            f"💰 PnL: <b>{sign}{net_usdt:.2f} USDT</b> ({sign}{total_pct:.2f}%)\n"
            f"🕑 Duration: {dur_str}"
        )
        pct = abs((mkt_price - self.risk.position.avg_price) / self.risk.position.avg_price * 100)
        msg += f"\nΔ%: {pct:.2f}%"
        print(f"[{self.symbol}] {exit_signal} close: {reason}")
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

    async def _set_sl(
        self, qty: float, sl_price: float, current_price: float | None = None
    ) -> None:
        """Place a reduce-only stop order and store its ``orderId``.

        ``current_price`` should be the latest traded price so the stop trigger
        is guaranteed to be below (or above for shorts) the actual market price
        at the moment of submission.  The latest price is re-checked after any
        existing stop is cancelled to avoid exchange rejections when the market
        moves quickly.
        """
        step = self.precision.step(self.client.http, self.symbol)
        qty_r = snap_qty(qty, step)

        current = current_price
        if current is None:
            current = self.close_window[-1] if self.close_window else None
        if current is not None:
            if self.risk.position.side == "Buy" and sl_price >= current:
                sl_price = current * 0.999
            elif self.risk.position.side == "Sell" and sl_price <= current:
                sl_price = current * 1.001

        # cancel previous SL order if any
        if self.sl_order_id:
            try:
                await self.client.cancel_order(
                    category="linear", symbol=self.symbol, orderId=self.sl_order_id
                )
            except Exception:
                pass

        # re-check price after cancel in case the market moved
        if self.close_window:
            current = self.close_window[-1]
            if self.risk.position.side == "Buy" and sl_price >= current:
                sl_price = current * 0.999
            elif self.risk.position.side == "Sell" and sl_price <= current:
                sl_price = current * 1.001

        link_id = self.client.gen_link_id("sl")
        resp = await self.client.create_reduce_only_sl(
            self.risk.position.side or "Buy", qty_r, sl_price, order_link_id=link_id
        )
        order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None

        self.current_sl_price = sl_price
        self.sl_order_id = order_id

    async def _set_tp_limit(self, qty: float, price: float) -> None:
        """Place a reduce-only TP limit order and store ``orderId``."""
        step = self.precision.step(self.client.http, self.symbol)
        qty_r = snap_qty(qty, step)
        if qty_r <= 0:
            return

        if self.tp_order_id:
            try:
                await self.client.cancel_order(
                    category="linear", symbol=self.symbol, orderId=self.tp_order_id
                )
            except Exception:
                pass

        side_close = "Sell" if self.risk.position.side == "Buy" else "Buy"
        resp = await self.client.create_limit_order(
            side_close, qty_r, price, reduce_only=True
        )
        order_id = resp.get("result", {}).get("orderId") if isinstance(resp, dict) else None
        self.tp_order_id = order_id

    async def _set_tp1(self, qty: float, price: float) -> None:
        await self._set_tp_limit(qty, price)

    async def _set_tp2(self, qty: float, price: float) -> None:
        await self._set_tp_limit(qty, price)

    async def _set_tp(self, qty: float, price: float) -> None:
        await self._set_tp_limit(qty, price)

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

    async def _wait_order_fill(self, order_id: str, timeout: float = 10.0, poll: float = 0.5) -> None:
        """Wait until ``order_id`` is no longer present in open orders."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                resp = await self.client.get_open_orders(category="linear", symbol=self.symbol)
                orders = resp.get("result", {}).get("list", [])
                if not any(o.get("orderId") == order_id for o in orders):
                    return
            except Exception:
                pass
            await asyncio.sleep(poll)
        print(f"[{self.symbol}] ⚠️ order {order_id} not filled within {timeout}s")

