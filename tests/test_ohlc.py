import asyncio
from src.symbol_engine import SymbolEngine
from tests.conftest import feed_trades


def test_one_bar(fixture_trades_5m):
    se = SymbolEngine("BTCUSDT")
    asyncio.run(feed_trades(se, fixture_trades_5m))
    assert se.ohlc.last_bar.close == fixture_trades_5m[-1].price
