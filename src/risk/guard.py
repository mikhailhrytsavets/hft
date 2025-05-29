from __future__ import annotations


class RiskGuard:
    """Simple global risk guard enforcing position and exposure limits."""

    MAX_POSITIONS: int = 8
    TOTAL_RISK_CAP_PCT: float = 20.0

    def __init__(self, account) -> None:
        self.account = account  # expects .equity_usd and .open_positions list

    def allow_new_position(self, size_usd: float, risk_pct: float) -> bool:
        if len(self.account.open_positions) >= self.MAX_POSITIONS:
            return False
        total = sum(p.risk_pct for p in self.account.open_positions) + risk_pct
        return total <= self.TOTAL_RISK_CAP_PCT

