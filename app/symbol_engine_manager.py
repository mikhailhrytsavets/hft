import asyncio
from types import SimpleNamespace as NS

from app.symbol_engine import SymbolEngine
from app.config import settings
from app.command_listener import telegram_command_listener
from app.exchange import BybitClient
from app.notifier import notify_telegram
from src.risk.guard import RiskGuard

class SymbolEngineManager:
    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.tasks: dict[str, asyncio.Task] = {}
        self.engines: dict[str, SymbolEngine] = {}
        self.account = NS(equity_usd=0.0, open_positions=[])
        self.guard = RiskGuard(self.account)
        if settings.risk.max_open_positions:
            self.guard.MAX_POSITIONS = settings.risk.max_open_positions
        if settings.trading.max_position_risk_percent:
            self.guard.TOTAL_RISK_CAP_PCT = settings.trading.max_position_risk_percent

    async def _run_engine(self, symbol: str):
        engine = SymbolEngine(symbol)
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
                engine = SymbolEngine(symbol)
                engine.manager = self
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

    async def _maybe_open_position(self, engine: SymbolEngine, direction: str, price: float) -> None:
        risk_pct = settings.trading.initial_risk_percent
        if not self.guard.allow_new_position(risk_pct):
            print("Portfolio risk cap hit")
            return
        await engine._open_position(direction, price)
        self.account.open_positions.append(NS(symbol=engine.symbol, risk_pct=risk_pct))

    def position_closed(self, engine: SymbolEngine) -> None:
        self.account.open_positions = [p for p in self.account.open_positions if p.symbol != engine.symbol]

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
