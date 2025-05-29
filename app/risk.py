from collections import deque
from datetime import datetime, timedelta, date
from pathlib import Path
from app.config import settings
from app.notifier import notify_telegram
from src.core.indicators import compute_rsi, compute_adx_info, compute_adx

from app.exchange import BybitClient

class Position:
    def __init__(self):
        self.reset()

    def reset(self):
        self.side = None
        self.qty = 0
        self.avg_price = 0
        self.open_time = None
        self.initial_qty = 0.0
        self.realized_pnl = 0.0
        self.entry_value = 0.0

class RiskManager:
    EQUITY_FILE = Path(__file__).parent.parent / "start_equity.txt"
    active_positions: set[str] = set()
    position_volumes: dict[str, float] = {}

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.position = Position()
        self.start_equity = None
        self.start_date: date | None = None
        self.dca_levels = 0
        self.tp1_done = False
        self.tp2_done = False
        self.trail_price = None
        self.best_price = None
        self.initial_qty = 0.0
        self.realized_pnl = 0.0
        self.entry_value = 0.0
        # store tuples of (high, low, close) for indicator calculations
        self.price_window = deque(maxlen=30)
        self.last_dca_price: float | None = None
        self.last_dca_time: datetime | None = None
        self.latest_spread_z: float = 0.0
        self.latest_vbd: float = 0.0
        self.last_htf_fetch: datetime | None = None
        self.last_htf_trend: str | None = None
        self._load_equity()

    # ------------------------------------------------------------------
    def _load_equity(self) -> None:
        try:
            if self.EQUITY_FILE.exists():
                raw = self.EQUITY_FILE.read_text().strip()
                if "," in raw:
                    val, ts = raw.split(",", 1)
                    self.start_equity = float(val)
                    try:
                        self.start_date = date.fromisoformat(ts)
                    except ValueError:
                        self.start_date = None
                else:
                    self.start_equity = float(raw)
                    self.start_date = None
        except Exception as exc:  # pragma: no cover - file i/o
            print(f"⚠️ Equity load failed: {exc}")

    def _save_equity(self) -> None:
        try:
            ts = (self.start_date or date.today()).isoformat()
            self.EQUITY_FILE.write_text(f"{self.start_equity},{ts}")
        except Exception as exc:  # pragma: no cover - file i/o
            print(f"⚠️ Equity save failed: {exc}")

    def reset_trade(self) -> None:
        self.tp1_done = False
        self.tp2_done = False
        self.trail_price = None
        self.best_price = None
        self.dca_levels = 0
        self.last_dca_price = None
        self.last_dca_time = None
        self.realized_pnl = 0.0
        self.initial_qty = self.position.qty
        self.entry_value = self.position.qty * self.position.avg_price

    @staticmethod
    def percent(current, reference):
        return (current - reference) / reference * 100 if reference else 0

    def _compute_rsi(self, period: int) -> float | None:
        closes = [c for _, _, c in self.price_window]
        return compute_rsi(closes, period)


    def _compute_adx_info(self, period: int) -> tuple[float | None, float | None, float | None]:
        closes = [c for _, _, c in self.price_window]
        return compute_adx_info(closes, period)

    def _compute_adx(self, period: int) -> float | None:
        closes = [c for _, _, c in self.price_window]
        return compute_adx(closes, period)

    def _need_dca(self, price: float, change: float, now: datetime) -> bool:
        stg = settings.trading

        if self.dca_levels >= stg.max_dca_levels:
            return False

        step_pct = stg.dca_step_percent
        base_step = step_pct * (self.dca_levels + 1) * (stg.dca_step_multiplier ** self.dca_levels)
        if self.position.side == "Buy":
            need = change <= -base_step
        else:
            need = change >= base_step

        if not need:
            return False

        if stg.max_dca_drawdown_percent:
            limit = stg.max_dca_drawdown_percent
            if (self.position.side == "Buy" and change <= -limit) or (
                self.position.side == "Sell" and change >= limit
            ):
                return False

        if self.last_dca_time and now - self.last_dca_time < timedelta(minutes=stg.dca_min_interval_minutes):
            return False

        if stg.enable_dca_adx_filter:
            adx, plus_di, minus_di = self._compute_adx_info(stg.adx_period)
            if adx and adx > stg.dca_adx_threshold:
                if (self.position.side == "Buy" and minus_di > plus_di) or (
                    self.position.side == "Sell" and plus_di > minus_di
                ):
                    return False

        if stg.enable_rsi_dca:
            rsi = self._compute_rsi(stg.rsi_period)
            if rsi is not None:
                if self.position.side == "Buy" and rsi > stg.rsi_oversold:
                    return False
                if self.position.side == "Sell" and rsi < stg.rsi_overbought:
                    return False
        if stg.enable_dca_spread_filter:
            if abs(self.latest_spread_z) > stg.dca_spread_threshold:
                return False
        if stg.enable_dca_vbd_filter:
            if self.position.side == "Buy" and self.latest_vbd < -stg.dca_vbd_threshold:
                return False
            if self.position.side == "Sell" and self.latest_vbd > stg.dca_vbd_threshold:
                return False
        if stg.use_htf_filter:
            try:
                if self.last_htf_fetch is None or now - self.last_htf_fetch > timedelta(seconds=60):
                    client = getattr(self, "_htf_client", None)
                    if client is None:
                        client = BybitClient(
                            self.symbol,
                            settings.bybit.api_key,
                            settings.bybit.api_secret,
                            settings.bybit.testnet,
                            settings.bybit.demo,
                            settings.bybit.channel_type,
                            settings.bybit.place_orders,
                        )
                        self._htf_client = client
                    resp = client.http.get_kline(
                        category="linear",
                        symbol=self.symbol,
                        interval=stg.htf_interval,
                        limit=1,
                    )
                    candle = resp.get("result", {}).get("list", [])[0]
                    open_price = float(candle.get("open") or candle.get("o"))
                    close_price = float(candle.get("close") or candle.get("c"))
                    self.last_htf_fetch = now
                    self.last_htf_trend = (
                        "UP" if close_price > open_price else "DOWN" if close_price < open_price else None
                    )
            except Exception as exc:
                print(f"[{self.symbol}] ⚠️ HTF fetch error: {exc}")
            if self.last_htf_trend:
                if self.position.side == "Buy" and self.last_htf_trend == "DOWN":
                    return False
                if self.position.side == "Sell" and self.last_htf_trend == "UP":
                    return False

        return True

    async def check_equity(self, current_equity):
        today = date.today()
        if self.start_equity is None or self.start_date != today:
            self.start_equity = current_equity
            self.start_date = today
            self._save_equity()
        drawdown = self.percent(current_equity, self.start_equity)
        if (
            settings.risk.enable_daily_drawdown_guard
            and drawdown <= settings.risk.daily_drawdown_percent
        ):
            await notify_telegram(
                f"🛑 Достигнут дневной лимит {drawdown:.2f}%. Бот остановлен."
            )
            return False

        profit = self.percent(current_equity, self.start_equity)
        if (
            settings.risk.enable_daily_profit_guard
            and settings.risk.daily_profit_percent
            and profit >= settings.risk.daily_profit_percent
        ):
            await notify_telegram(
                f"🛑 Достигнут дневной профит {profit:.2f}%. Бот остановлен."
            )
            return False
        return True

    async def check_exit(self, price):
        if self.position.qty == 0:
            return None
        change = self.percent(price, self.position.avg_price)

        # Break-even move
        if (
            settings.trading.break_even_after_percent
            and not self.tp1_done
        ):
            be = settings.trading.break_even_after_percent
            hit_be = (
                self.position.side == "Buy" and change >= be
            ) or (
                self.position.side == "Sell" and change <= -be
            )
            if hit_be:
                self.tp1_done = True
                self.trail_price = self.position.avg_price
                self.best_price = price

        # Break-even by time
        if (
            settings.trading.break_even_after_minutes > 0
            and not self.tp1_done
            and datetime.utcnow() - self.position.open_time >= timedelta(minutes=settings.trading.break_even_after_minutes)
        ):
            minp = settings.trading.min_profit_to_be
            if (
                self.position.side == "Buy" and change >= minp
            ) or (
                self.position.side == "Sell" and change <= -minp
            ):
                self.tp1_done = True
                self.trail_price = self.position.avg_price
                self.best_price = price

        # Hard timeout
        if (
            settings.trading.enable_position_timeout
            and settings.trading.max_position_minutes > 0
            and datetime.utcnow() - self.position.open_time
            > timedelta(minutes=settings.trading.max_position_minutes)
        ):
            return "TIMEOUT"

        # Fallback TP when partial TPs are disabled
        if settings.trading.tp1_percent is None and settings.trading.tp2_percent is None:
            tp_pct = settings.trading.take_profit_percent
            if (
                self.position.side == "Buy" and change >= tp_pct
            ) or (
                self.position.side == "Sell" and change <= -tp_pct
            ):
                return "TP"

        # TP1
        if not self.tp1_done:
            if (
                self.position.side == "Buy" and change >= settings.trading.tp1_percent
            ) or (
                self.position.side == "Sell" and change <= -settings.trading.tp1_percent
            ):
                self.tp1_done = True
                self.best_price = price
                self.trail_price = self.position.avg_price
                return "TP1"
        if self.tp1_done and not self.tp2_done:
            if settings.trading.tp2_percent is not None:
                if (
                    self.position.side == "Buy" and change >= settings.trading.tp2_percent
                ) or (
                    self.position.side == "Sell" and change <= -settings.trading.tp2_percent
                ):
                    self.tp2_done = True
                    self.best_price = price
                    return "TP2"

        # trailing update
        if self.tp1_done and (settings.trading.tp2_percent is None or self.tp2_done):
            if self.position.side == "Buy":
                self.best_price = max(self.best_price or price, price)
                new_trail = self.best_price * (1 - settings.trading.trailing_distance_percent / 100)
                if self.trail_price is None or new_trail > self.trail_price:
                    self.trail_price = new_trail
                if price <= self.trail_price:
                    return "TRAIL"
            else:
                self.best_price = min(self.best_price or price, price)
                new_trail = self.best_price * (1 + settings.trading.trailing_distance_percent / 100)
                if self.trail_price is None or new_trail < self.trail_price:
                    self.trail_price = new_trail
                if price >= self.trail_price:
                    return "TRAIL"

        # TP
        if (
            self.position.side == "Buy" and change >= settings.trading.take_profit_percent
        ) or (
            self.position.side == "Sell" and change <= -settings.trading.take_profit_percent
        ):
            return "TP"

        # DCA
        if self._need_dca(price, change, datetime.utcnow()):
            self.dca_levels += 1
            self.last_dca_price = price
            self.last_dca_time = datetime.utcnow()
            return "DCA"

        # Soft SL — по времени
        if settings.trading.soft_sl_minutes > 0:
            if datetime.utcnow() - self.position.open_time > timedelta(minutes=settings.trading.soft_sl_minutes):
                if (self.position.side == "Buy" and change < 0) or (
                    self.position.side == "Sell" and change > 0
                ):
                    return "SOFT_SL"

        # Soft SL — по убытку
        if (self.position.side == "Buy" and change <= settings.trading.soft_sl_percent) or \
           (self.position.side == "Sell" and change >= -settings.trading.soft_sl_percent):
            return "SOFT_SL"

        return None
