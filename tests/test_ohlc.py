from app.core.data import OHLCCollector


async def feed_collector(col, trades):
    for t in trades:
        col.on_trade(t.price, t.qty, t.ts)


def test_one_bar(fixture_trades_5m):
    col = OHLCCollector()
    import asyncio
    asyncio.run(feed_collector(col, fixture_trades_5m))
    assert col.last_bar.close == fixture_trades_5m[-1].price
