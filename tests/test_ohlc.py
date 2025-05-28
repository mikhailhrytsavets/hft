import asyncio
from collections import namedtuple
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(root))

import types
from types import SimpleNamespace
cfg = types.ModuleType('app.config')
cfg.settings = SimpleNamespace(
    bybit=SimpleNamespace(api_key='', api_secret='', symbols=['BTCUSDT'], testnet=False, demo=False, channel_type='linear'),
    trading=SimpleNamespace(leverage=1, rsi_period=14, adx_period=14,
                                 enable_hedging=False),
    entry_score=SimpleNamespace(symbol_weights={}, weights={}, symbol_threshold_k={}, threshold_k=1.0),
    multi_tf=SimpleNamespace(enable=False, intervals=[], trend_confirm_bars=1, weights={}),
)
sys.modules['app.config'] = cfg

import pytest

from app.symbol_engine import SymbolEngine

Trade = namedtuple('Trade', 'price qty ts')

fixture_trades_5m = [Trade(100 + i, 1.0, i * 60_000) for i in range(5)]

async def feed_trades(engine, trades):
    for t in trades:
        engine._on_trades([{"p": t.price, "v": t.qty, "S": "Buy", "T": t.ts}])
        await asyncio.sleep(0)

@pytest.fixture
def engine(monkeypatch):
    from app.exchange import BybitClient
    monkeypatch.setattr(BybitClient, "set_leverage", lambda *a, **k: None)
    monkeypatch.setattr(SymbolEngine, "_restore_position", lambda self: None)
    monkeypatch.setattr(SymbolEngine, "_purge_stale_orders", lambda self: None)
    return SymbolEngine("BTCUSDT")

def test_one_bar(engine):
    asyncio.run(feed_trades(engine, fixture_trades_5m))
    assert engine.ohlc.last_bar.close == fixture_trades_5m[-1].price
