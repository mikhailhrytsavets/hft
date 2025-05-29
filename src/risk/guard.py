from __future__ import annotations

"""Global risk guard enforcing position and equity limits."""

class RiskGuard:
    """Track aggregate risk and daily PnL to block trading when limits hit."""

    MAX_POSITIONS = 8
    TOTAL_RISK_CAP_PCT = 20.0  # of account equity
    DD_LOCK_PCT = -5.0
    PROFIT_LOCK_PCT = 5.0

    def __init__(self, account) -> None:
        self.account = account  # expects ``equity_usd`` and ``open_positions``
        self.day_start_equity = account.equity_usd
        self.daily_pnl = 0.0
        self.dd_lock = False
        self.profit_lock = False

    def update_daily_pnl(self, pnl: float) -> None:
        self.daily_pnl += pnl
        pct = self.daily_pnl / self.day_start_equity * 100 if self.day_start_equity else 0
        if pct <= self.DD_LOCK_PCT:
            self.dd_lock = True
        if pct >= self.PROFIT_LOCK_PCT:
            self.profit_lock = True

    def allow_new_position(self, symbol: str, risk_pct: float) -> bool:
        """Return True if opening a new position is allowed."""
        if self.dd_lock or self.profit_lock:
            return False
        if len(self.account.open_positions) >= self.MAX_POSITIONS:
            return False
        total = sum(p.risk_pct for p in self.account.open_positions) + risk_pct
        return total <= self.TOTAL_RISK_CAP_PCT
