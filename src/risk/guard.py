from __future__ import annotations

"""Global risk guard enforcing position and equity limits."""

class RiskGuard:
    """Simple guard tracking open positions and aggregate risk."""

    MAX_POSITIONS = 8
    TOTAL_RISK_CAP_PCT = 20.0  # of account equity

    def __init__(self, account) -> None:
        self.account = account  # expects ``equity_usd`` and ``open_positions``

    def allow_new_position(self, size_usd: float, risk_pct: float) -> bool:
        """Return ``True`` if a new position may be opened."""
        if len(self.account.open_positions) >= self.MAX_POSITIONS:
            return False
        total = sum(p.risk_pct for p in self.account.open_positions) + risk_pct
        return total <= self.TOTAL_RISK_CAP_PCT
