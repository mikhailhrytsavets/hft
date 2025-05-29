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


class DummyEngine:
    def __init__(self):
        self.opened = False

    async def _open_position(self, *args):
        self.opened = True


class DummyManager:
    def __init__(self, limit):
        self.account = NS(equity_usd=0, open_positions=[])
        self.guard = RiskGuard(self.account)
        self.guard.TOTAL_RISK_CAP_PCT = limit

    async def maybe_open(self, engine, risk_pct):
        if not self.guard.allow_new_position(risk_pct):
            return False
        self.account.open_positions.append(NS(risk_pct=risk_pct))
        await engine._open_position(None)
        return True


def test_manager_blocks_second_entry():
    mgr = DummyManager(limit=0.3)
    e1, e2 = DummyEngine(), DummyEngine()
    import asyncio
    asyncio.run(mgr.maybe_open(e1, 0.25))
    assert e1.opened
    asyncio.run(mgr.maybe_open(e2, 0.25))
    assert not e2.opened
