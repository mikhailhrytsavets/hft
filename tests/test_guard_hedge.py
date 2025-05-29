from src.strategy.hedge import counterpart, should_open, should_close
from src.risk.guard import RiskGuard
from types import SimpleNamespace as NS


def test_counterpart():
    assert counterpart("SOLUSDT")[0] == "BTCUSDT"


def test_risk_cap():
    acc = NS(equity_usd=10000, open_positions=[NS(risk_pct=4)] * 5)
    guard = RiskGuard(acc)
    assert not guard.allow_new_position(1000, 1)


def test_hedge_logic():
    assert should_open("LONG", 32, 28, 3, 1, 18)
    assert should_close(+1.1, 1, 24, 30, "LONG")
