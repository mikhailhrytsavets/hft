import asyncio
import logging
from types import SimpleNamespace
from app.symbol_engine import SymbolEngine
from app.config import settings
from app.command_listener import telegram_command_listener
from app.exchange import BybitClient
from app.notifier import notify_telegram
from src.risk.guard import RiskGuard

logger = logging.getLogger(__name__)

class SymbolEngineManager:
    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.tasks: dict[str, asyncio.Task] = {}
        self.engines: dict[str, SymbolEngine] = {}
        self.account = SimpleNamespace(equity_usd=0.0, open_positions=[])
        self.guard = RiskGuard(self.account)

    def _patch_engine(self, engine: SymbolEngine) -> None:
        original = engine._open_position

        async def guarded(direction: str, price: float):
            pct = settings.trading.initial_risk_percent
            if self.guard.allow_new_position(engine.symbol, pct):
                self.account.open_positions.append(
                    SimpleNamespace(symbol=engine.symbol, risk_pct=pct)
                )
                await original(direction, price)
            else:
                logger.info("Portfolio risk cap hit")

        engine._open_position = guarded

    async def _run_engine(self, symbol: str):
        engine = SymbolEngine(symbol)
        self._patch_engine(engine)
        self.engines[symbol] = engine
        attempt = 0
        while True:
            try:
                await engine.run()
            except Exception as exc:
                attempt += 1
                wait = min(2 ** attempt, 64)
                logger.error(f"[{symbol}] ❌ Engine crashed: {exc} → restart in {wait}s")
                await notify_telegram(f"❌ Engine {symbol} crashed: {exc}")
                await asyncio.sleep(wait)
                engine = SymbolEngine(symbol)
                self._patch_engine(engine)
                self.engines[symbol] = engine
            else:
                attempt = 0

    async def start_all(self):
        for symbol in self.symbols:
            self.tasks[symbol] = asyncio.create_task(self._run_engine(symbol))

        # shared WS connections ----------------------------------------
        self.tasks["orderbook"] = asyncio.create_task(
            BybitClient.ws_multi(self.symbols, "orderbook.50", self._on_orderbook)
        )
        self.tasks["trades"] = asyncio.create_task(
            BybitClient.ws_multi(self.symbols, "publicTrade", self._on_trades)
        )

        self.tasks["cmd"] = asyncio.create_task(telegram_command_listener())
        await asyncio.gather(*self.tasks.values())

    def _on_orderbook(self, symbol: str, data):
        engine = self.engines.get(symbol)
        if engine:
            engine._on_orderbook(data)

    def _on_trades(self, symbol: str, data):
        engine = self.engines.get(symbol)
        if engine:
            engine._on_trades(data)

async def run_multi_symbol_bot():
    symbols = settings.bybit.symbols
    manager = SymbolEngineManager(symbols)
    await manager.start_all()
