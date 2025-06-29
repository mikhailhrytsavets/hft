import asyncio

from app.simple_engine import SymbolEngine
from strategy.entry import BounceEntry, Signal as EntrySignal
from strategy.dca import SmartDCA
from core.market_data import Bar
from app import indicators


def test_entry_dca_exit(monkeypatch):
    se = SymbolEngine("BTCUSDT")

    # patch indicators for deterministic behaviour
    monkeypatch.setattr(indicators, "atr", lambda *a, **k: 1.0)

    signals = [EntrySignal.LONG, EntrySignal.FLAT, EntrySignal.FLAT]

    def fake_sig(*args, **kwargs):
        return signals.pop(0)

    monkeypatch.setattr(BounceEntry, "generate_signal", staticmethod(fake_sig))
    monkeypatch.setattr(SmartDCA, "allowed", staticmethod(lambda *a, **k: True))
    monkeypatch.setattr(SmartDCA, "next_price", staticmethod(lambda *a, **k: 99))

    bar1 = Bar(100, 101, 99, 100, 1, 0, 300)
    bar2 = Bar(99, 100, 98, 99, 1, 300, 600)
    bar3 = Bar(102, 103, 101, 102, 1, 600, 900)

    asyncio.run(se._on_bar(bar1))
    assert se.pm.state.qty == 1

    asyncio.run(se._on_bar(bar2))
    assert se.pm.state.qty == 2

    asyncio.run(se._on_bar(bar3))
    assert se.pm.closed_qty > 0
