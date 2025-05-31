from legacy.strategy.manager import PositionManager
import pytest


def test_tp1_trailing():
    pm = PositionManager(tp1_ratio=0.4)
    pm.open(side="LONG", qty=1, entry=100, atr=2)
    assert pm.tp1 == 102
    pm.on_tick(102.1)
    assert pm.closed_qty == pytest.approx(0.4, rel=1e-2)
    assert pm.trailing_started
    pm.on_tick(104.1)
    assert pm.closed_qty == pytest.approx(0.7, rel=1e-2)
    pm.on_tick(105.0)
    trail = pm.trail_price
    assert trail and trail > 0
    pm.on_tick(trail - 0.01)
    assert pm.state.qty == 0


def test_add_updates_entry():
    pm = PositionManager()
    pm.open(side="LONG", qty=1, entry=100, atr=2)
    pm.add(1, 98)
    assert pm.state.qty == 2
    assert pm.initial_qty == 2
    assert pm.state.entry == pytest.approx(99, rel=1e-2)
    assert pm.sl == pytest.approx(pm.state.entry - pm.sl_atr * pm.state.atr)
