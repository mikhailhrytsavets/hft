import sys
import types

# minimal settings stub
trading = types.SimpleNamespace(
    strategy_mode="hybrid",
    leverage=1,
    enable_hedging=False,
    candle_interval_sec=1,
    rsi_period=14,
    adx_period=14,
    initial_risk_percent=1.0,
    max_position_risk_percent=0,
    max_dca_levels=1,
)
entry_score = types.SimpleNamespace(symbol_weights={}, weights={}, threshold_k=1.0, symbol_threshold_k={})
settings_stub = types.SimpleNamespace(
    bybit=types.SimpleNamespace(api_key="", api_secret="", testnet=False, demo=False, place_orders=False, channel_type="linear", symbols=["BTCUSDT"]),
    trading=trading,
    risk=types.SimpleNamespace(max_open_positions=0, daily_trades_limit=0, enable_daily_trades_guard=False),
    telegram=None,
    entry_score=entry_score,
    multi_tf=types.SimpleNamespace(enable=False, intervals=[]),
    symbol_params={},
)

sys.modules['app.config'] = types.SimpleNamespace(settings=settings_stub)


class DummyClient:
    def __init__(self, symbol, api_key="", api_secret="", testnet=False, demo=False, channel_type="linear", place_orders=True):
        self.symbol = symbol
        self.http = types.SimpleNamespace(api_key=api_key, api_secret=api_secret, testnet=testnet, demo=demo)
        self.place_orders = place_orders
        self.channel_type = channel_type

    def set_leverage(self, *a, **k):
        pass

sys.modules['app.exchange'] = types.SimpleNamespace(BybitClient=DummyClient)

from app.symbol_engine_manager import SymbolEngineManager, HybridStrategyEngine, SymbolEngine


def test_engine_class_hybrid():
    mgr = SymbolEngineManager(["BTCUSDT"])
    assert mgr._engine_class() is HybridStrategyEngine


def test_engine_class_basic():
    settings_stub.trading.strategy_mode = "basic"
    mgr = SymbolEngineManager(["BTCUSDT"])
    assert mgr._engine_class() is SymbolEngine
