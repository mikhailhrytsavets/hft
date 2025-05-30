from __future__ import annotations

from datetime import date


class RiskGuard:
    """Portfolio guard: max positions, total risk and daily trades cap."""

    MAX_POSITIONS = 8
    TOTAL_RISK_CAP_PCT = 20.0  # % of account equity

    DAILY_TRADES_LIMIT = 0  # from settings.toml
    DAY_DRAWDOWN_LOCK = -5.0  # %

    def __init__(self, account):
        from app.config import settings

        self.account = account
        self.today_date = date.today()
        self.today_trades = 0

        # ``settings.risk`` can be either a model or a plain dict in tests
        risk_cfg = getattr(settings, "risk", {})
        if isinstance(risk_cfg, dict):
            self.DAILY_TRADES_LIMIT = risk_cfg.get("daily_trades_limit", 0)
        else:
            self.DAILY_TRADES_LIMIT = getattr(risk_cfg, "daily_trades_limit", 0)

    # ---------- day-roll helpers ----------
    def _roll_day(self) -> None:
        if date.today() != self.today_date:
            self.today_date = date.today()
            self.today_trades = 0

    # ---------- public API ----------
    def inc_trade(self) -> None:
        self._roll_day()
        self.today_trades += 1

    def allow_new_position(self, new_risk_pct: float) -> bool:
        self._roll_day()

        if (
            self.DAILY_TRADES_LIMIT
            and self.today_trades >= self.DAILY_TRADES_LIMIT
        ):
            return False

        if len(self.account.open_positions) >= self.MAX_POSITIONS:
            return False

        total = sum(p.risk_pct for p in self.account.open_positions)
        return total + new_risk_pct <= self.TOTAL_RISK_CAP_PCT
