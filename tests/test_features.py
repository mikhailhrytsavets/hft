import asyncio
from legacy.market_features import MarketFeatures


def test_spread_z(fixture_21_bars):
    mf = MarketFeatures()
    for i, bar in enumerate(fixture_21_bars):
        mf.update_spread(1.0, 1.0 + i * 0.01)
        mf.compute_obi([[1,1]], [[1,1]])
        mf.update_vbd(1, 1)
        asyncio.run(mf.on_bar(bar))
    z = mf.snapshot()["spread_z"]
    assert abs(z) < 5


def test_update_volatility():
    mf = MarketFeatures()
    prices = [10 + i * 0.1 for i in range(10)]
    vol = 0.0
    for p in prices:
        vol = mf.update_volatility(p)
    assert mf.price_window[-1] == prices[-1]
    assert vol >= 0
