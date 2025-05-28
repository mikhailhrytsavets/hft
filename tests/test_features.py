import asyncio
from src.market_features import MarketFeatures
from tests.conftest import fixture_21_bars


def test_spread_z(fixture_21_bars):
    mf = MarketFeatures()
    for i, bar in enumerate(fixture_21_bars):
        mf.update_spread(1.0, 1.0 + i * 0.01)
        mf.compute_obi([[1,1]], [[1,1]])
        mf.update_vbd(1, 1)
        asyncio.run(mf.on_bar(bar))
    z = mf.snapshot()["spread_z"]
    assert abs(z) < 5
