import asyncio
import os
import sys
import types
from collections import namedtuple

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from legacy.core.data import Bar
pybit = types.ModuleType("pybit")
pybit.exceptions = types.SimpleNamespace(InvalidRequestError=Exception)
sys.modules.setdefault("pybit", pybit)
sys.modules.setdefault("pybit.exceptions", pybit.exceptions)
# stub pybit.unified_trading.HTTP
class _HTTP:
    def __init__(self, *a, **k):
        pass

pybit.unified_trading = types.SimpleNamespace(HTTP=_HTTP)
sys.modules.setdefault("pybit.unified_trading", pybit.unified_trading)
# minimal pydantic stub
pydantic = types.ModuleType("pydantic")

class _FakeModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

pydantic.BaseModel = _FakeModel
sys.modules.setdefault("pydantic", pydantic)
# stub aiosqlite
sys.modules.setdefault("aiosqlite", types.ModuleType("aiosqlite"))
sys.modules.setdefault("websockets", types.ModuleType("websockets"))
req_mod = types.ModuleType("requests")
req_mod.ReadTimeout = Exception
req_mod.ConnectionError = Exception
sys.modules.setdefault("requests", req_mod)
urllib3_mod = types.ModuleType("urllib3")
urllib3_mod.exceptions = types.SimpleNamespace(ProtocolError=Exception)
sys.modules.setdefault("urllib3", urllib3_mod)
aiohttp_mod = types.ModuleType("aiohttp")
aiohttp_mod.ClientSession = object
sys.modules.setdefault("aiohttp", aiohttp_mod)

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
