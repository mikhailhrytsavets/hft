from types import SimpleNamespace as NS
import logging
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


def test_manager_guard_blocks(caplog):
    acc = NS(equity_usd=10000, open_positions=[])
    guard = RiskGuard(acc)

    class DummyEngine:
        def __init__(self):
            self.opened = 0

        async def _open_position(self, *_):
            self.opened += 1

    async def maybe_open(engine, pct):
        if guard.allow_new_position(pct):
            acc.open_positions.append(NS(risk_pct=pct))
            await engine._open_position("LONG", 1.0)
        else:
            logging.getLogger(__name__).info("Portfolio risk cap hit")

    import asyncio, logging
    e1, e2 = DummyEngine(), DummyEngine()
    asyncio.run(maybe_open(e1, 15))
    with caplog.at_level(logging.INFO):
        asyncio.run(maybe_open(e2, 10))
    assert e1.opened == 1
    assert e2.opened == 0
    assert "Portfolio risk cap hit" in caplog.text
