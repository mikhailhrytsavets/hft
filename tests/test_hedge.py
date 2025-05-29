import asyncio
from types import SimpleNamespace

from src.strategy.hedge import HEDGE_MAP, HedgeGuard


def test_mapping():
    assert HEDGE_MAP["BTCUSDT"][0] == "ETHUSDT"
    assert HEDGE_MAP.get("DOGEUSDT", HEDGE_MAP["default"])[0] == "BTCUSDT"


class Dummy(HedgeGuard):
    def __init__(self):
        self.unrealised_dd = 0.0
        self.opened = False
        self.closed = False

    def _last_price(self, symbol: str) -> float:
        return 1.0

    async def _open_hedge(self, sym: str, qty: float, side: str) -> None:
        self.opened = True
        self.open_args = (sym, qty, side)

    async def _close_hedge(self) -> None:
        self.closed = True

    def _hedge_pnl(self) -> float:
        return self.pnl


def test_trigger_open_and_close():
    d = Dummy()
    pos = SimpleNamespace(symbol="BTCUSDT", side="LONG", notional_value=100)
    d.unrealised_dd = 2.0
    d.pnl = 0.0
    asyncio.run(d.maybe_hedge(pos, adx_now=31, atr=1, rsi=10))
    assert d.opened and d.hedge_active
    d.pnl = 1.1
    asyncio.run(d.maybe_hedge(pos, adx_now=24, atr=1, rsi=10))
    assert d.closed and not d.hedge_active
