import asyncio
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import types
pybit = types.ModuleType("pybit")
pybit.exceptions = types.SimpleNamespace(InvalidRequestError=Exception)
sys.modules.setdefault("pybit", pybit)
sys.modules.setdefault("pybit.exceptions", pybit.exceptions)
from collections import namedtuple
import pytest

from src.core.data import Bar

Trade = namedtuple("Trade", "price qty ts")

@pytest.fixture
def fixture_trades_5m():
    return [
        Trade(10.0, 1.0, 0),
        Trade(12.0, 0.5, 60),
        Trade(9.0, 1.5, 299),
        Trade(11.0, 0.2, 300),
    ]

@pytest.fixture
def fixture_21_bars():
    bars = []
    start = 0
    price = 100.0
    for i in range(21):
        bar = Bar(price, price + 1, price - 1, price + 0.5, 1.0, start, start + 300)
        bars.append(bar)
        start += 300
        price += 1
    return bars

async def feed_trades(engine, trades):
    for t in trades:
        engine.ohlc.on_trade(t.price, t.qty, t.ts)
    await asyncio.sleep(0)
