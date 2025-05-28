from src.core.data import OHLCCollector, Bar
from src.market_features import MarketFeatures

class SymbolEngine:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.ohlc = OHLCCollector()
        self.market = MarketFeatures()
        self.ohlc.subscribe(self._on_bar)

    async def _on_bar(self, bar: Bar) -> None:
        await self.market.on_bar(bar)
