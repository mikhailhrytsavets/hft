import asyncio
import pathlib
import sys

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from src.core.data import Bar
from app.market_features import MarketFeatures

fixture_21_bars = [
    Bar(i + 1, i + 1, i + 1, i + 1, 1.0, i * 300000, (i + 1) * 300000) for i in range(21)
]

def test_spread_z():
    mf = MarketFeatures()

    async def feed():
        for bar in fixture_21_bars:
            await mf.on_bar(bar)
    asyncio.run(feed())
    z = mf.snapshot()["spread_z"]
    assert abs(z) < 5
