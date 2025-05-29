from types import SimpleNamespace as NS
from src.risk.guard import RiskGuard


def test_block_by_count():
    acc = NS(equity_usd=10000, open_positions=[NS(risk_pct=2)] * 8)
    guard = RiskGuard(acc)
    assert not guard.allow_new_position(1)


def test_block_by_risk():
    acc = NS(equity_usd=10000, open_positions=[NS(risk_pct=5)] * 3)
    guard = RiskGuard(acc)
    assert not guard.allow_new_position(6)


def test_dd_lock():
    acc = NS(equity_usd=10000, open_positions=[])
    g = RiskGuard(acc)
    g.update_daily_pnl(-600)
    assert not g.allow_new_position(1)
