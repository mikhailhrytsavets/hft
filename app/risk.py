# Refactored on 2024-06-06 to remove legacy coupling
from collections import deque
from datetime import datetime, timedelta, date
from pathlib import Path
import time
import logging
from app.config import settings, SymbolParams
from app.notifier import notify_telegram
from app.indicators import (
    compute_rsi,
    compute_adx_info,
    compute_adx,
    atr as compute_atr,
)
from app import exit as exit_logic

from app.exchange import BybitClient

logger = logging.getLogger(__name__)

from dataclasses import dataclass


@dataclass
class OrderFill:
    qty: float
    price: float
    side: str
    pnl: float = 0.0



@dataclass
class Position:
    side: str | None = None
    qty: float = 0.0
    avg_price: float = 0.0
    open_time: datetime | None = None
    realized_pnl: float = 0.0
    dca_count: int = 0

    def reset(self) -> None:
        """Clear all position information."""
        self.side = None
        self.qty = 0.0
        self.avg_price = 0.0
        self.open_time = None
        self.realized_pnl = 0.0
        self.dca_count = 0

class RiskManager:
    EQUITY_FILE = Path(__file__).parent.parent / "start_equity.txt"

    def __init__(self, symbol: str, manager=None):
        self.symbol = symbol
        self.manager = manager
        if manager is not None:
            self.active_positions = manager.active_positions
            self.position_volumes = manager.position_volumes
        else:
            self.active_positions: set[str] = set()
            self.position_volumes: dict[str, float] = {}
        self.today_trades: int = 0
        self.today_date: date = date.today()
        self.position = Position()
        self.start_equity = None
        self.start_date: date | None = None
        self.dca_levels = 0
        self.tp1_done = False
        self.tp2_done = False
        self.trail_price = None
        self.best_price = None
        self.last_trail_update = None
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
        self._last_atr_log: float = 0.0

    def update_after_fill(self, fill: "OrderFill") -> None:
        if fill.side == "Buy":
            total = self.position.avg_price * self.position.qty + fill.price * fill.qty
            self.position.qty += fill.qty
            self.position.avg_price = total / self.position.qty
        else:
            self.position.qty -= fill.qty
        self.position.realized_pnl += fill.pnl
        self.position.dca_count += 1

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
            logger.warning("Equity load failed: %s", exc)

    def _save_equity(self) -> None:
        try:
            ts = (self.start_date or date.today()).isoformat()
            self.EQUITY_FILE.write_text(f"{self.start_equity},{ts}")
        except Exception as exc:  # pragma: no cover - file i/o
            logger.warning("Equity save failed: %s", exc)

    def reset_trade(self) -> None:
        self.tp1_done = False
        self.tp2_done = False
        self.trail_price = None
        self.best_price = None
        self.last_trail_update = None
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

    def _compute_atr(self, period: int) -> float:
        highs = [h for h, _, _ in self.price_window]
        lows = [l for _, l, _ in self.price_window]
        closes = [c for _, _, c in self.price_window]
        return compute_atr(highs, lows, closes, period)

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
                logger.warning("[%s] HTF fetch error: %s", self.symbol, exc)
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
        """Delegate exit checks to :mod:`app.exit`."""
        return await exit_logic.check_exit(self, price)

    # ----- day-trade counter -----
    def inc_trade(self):
        if date.today() != self.today_date:
            self.today_date = date.today()
            self.today_trades = 0
        self.today_trades += 1

