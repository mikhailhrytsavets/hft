import asyncio
from types import SimpleNamespace as NS

from app.mean_reversion_engine import MeanReversionEngine
from app.config import settings
from app.notifier import notify_telegram
from app.risk_guard import RiskGuard

class SymbolEngineManager:
    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.tasks: dict[str, asyncio.Task] = {}
        self.engines: dict[str, MeanReversionEngine] = {}
        self.account = NS(equity_usd=0.0, open_positions=[])
        self.guard = RiskGuard(self.account)
        if settings.risk.max_open_positions:
            self.guard.MAX_POSITIONS = settings.risk.max_open_positions
        if settings.trading.max_position_risk_percent:
            self.guard.TOTAL_RISK_CAP_PCT = settings.trading.max_position_risk_percent
        if settings.risk.daily_trades_limit:
            self.guard.DAILY_TRADES_LIMIT = settings.risk.daily_trades_limit


    def _engine_class(self) -> type[MeanReversionEngine]:
        return MeanReversionEngine

    async def _run_engine(self, symbol: str, ref_symbol: str | None = None):
        engine_cls = self._engine_class()
        engine = engine_cls(symbol)
        engine.manager = self
        self.engines[symbol] = engine
        attempt = 0
        while True:
            try:
                await engine.run()
            except Exception as exc:
                attempt += 1
                wait = min(2 ** attempt, 64)
                print(f"[{symbol}] ❌ Engine crashed: {exc} → restart in {wait}s")
                await notify_telegram(f"❌ Engine {symbol} crashed: {exc}")
                await asyncio.sleep(wait)
                engine_cls = self._engine_class()
                engine = engine_cls(symbol)
                engine.manager = self
                self.engines[symbol] = engine
            else:
                attempt = 0

    async def start_all(self):
        for symbol in self.symbols:
            self.tasks[symbol] = asyncio.create_task(self._run_engine(symbol))
        await asyncio.gather(*self.tasks.values())

    def position_closed(self, engine: MeanReversionEngine) -> None:
        self.account.open_positions = [p for p in self.account.open_positions if p.symbol != engine.symbol]

async def run_multi_symbol_bot():
    symbols = settings.bybit.symbols
    manager = SymbolEngineManager(symbols)
    await manager.start_all()

