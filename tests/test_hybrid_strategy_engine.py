import math
import pytest
import types
import sys
import asyncio

# provide minimal settings stub before importing engine
trading = types.SimpleNamespace(leverage=1, enable_hedging=False, candle_interval_sec=1,
                                rsi_period=14, adx_period=14)
entry_score = types.SimpleNamespace(symbol_weights={}, weights={}, threshold_k=1.0, symbol_threshold_k={})
settings_stub = types.SimpleNamespace(bybit=types.SimpleNamespace(api_key="", api_secret="", testnet=False, demo=False, place_orders=False, channel_type="linear"),
                                      trading=trading, risk=types.SimpleNamespace(max_open_positions=0), telegram=None, entry_score=entry_score, multi_tf=types.SimpleNamespace(enable=False, intervals=[]), symbol_params={})
sys.modules['app.config'] = types.SimpleNamespace(settings=settings_stub)

class DummyClient:
    def __init__(self, symbol, api_key="", api_secret="", testnet=False, demo=False, channel_type="linear", place_orders=True):
        self.symbol = symbol
        self.http = types.SimpleNamespace(api_key=api_key, api_secret=api_secret, testnet=testnet, demo=demo,
                                          get_positions=lambda category, symbol: {"result": {"list": [{}]}},
                                          get_open_orders=lambda category, symbol: {"result": {"list": []}})
        self.place_orders = place_orders
        self.channel_type = channel_type

    def set_leverage(self, *a, **k):
        print(f"[{self.symbol}] \u274c set_leverage suppressed")

    async def price_stream(self, *a, **k):
        if False:
            yield 0

sys.modules['app.exchange'] = types.SimpleNamespace(BybitClient=DummyClient)

from app.hybrid_strategy_engine import HybridStrategyEngine  # noqa: E402
from app.symbol_engine import SymbolEngine


def test_initialization_and_attributes():
    engine = HybridStrategyEngine("BTCUSDT", "ETHUSDT")
    assert engine.symbol == "BTCUSDT"
    assert engine.ref_symbol == "ETHUSDT"
    assert engine.client.symbol == "BTCUSDT"
    assert engine.ref_client.symbol == "ETHUSDT"
    assert engine.risk.position.qty == 0
    assert engine.ref_risk.position.qty == 0


def test_ml_evaluate_signal_placeholder():
    engine = HybridStrategyEngine("BTCUSDT")
    assert engine._ml_evaluate_signal() is True


def test_momentum_filter_logic():
    engine = HybridStrategyEngine("BTCUSDT")
    engine.market.price_window.extend([100.0, 99.0, 98.0, 97.0, 96.0])
    assert engine._momentum_ok("LONG") is False
    assert engine._momentum_ok("SHORT") is True


def test_spread_zscore_computation():
    engine = HybridStrategyEngine("BTCUSDT", "ETHUSDT")
    main_prices = [100, 102, 101, 99, 100]
    ref_prices = [50, 51, 50.5, 49, 50]
    for pm, pr in zip(main_prices, ref_prices):
        if engine.ref_price is None:
            engine.ref_price = pr
        log_ratio = math.log(pm) - math.log(pr)
        engine.spread_history.append(log_ratio)
    if len(engine.spread_history) > 1:
        mean = sum(engine.spread_history) / len(engine.spread_history)
        var = sum((x - mean) ** 2 for x in engine.spread_history) / len(engine.spread_history)
        z = (engine.spread_history[-1] - mean) / (math.sqrt(var) if var > 0 else 1)
        assert abs(z) < 1.0


@pytest.mark.asyncio
async def test_mm_and_stat_arb_activation(monkeypatch):
    trading.enable_mm = True
    trading.enable_stat_arb = True

    async def dummy_ws(*args, **kwargs):
        return None

    monkeypatch.setattr(sys.modules['app.exchange'].BybitClient, 'ws_multi', dummy_ws)
    async def dummy_run(self):
        return
    monkeypatch.setattr(sys.modules['app.hybrid_strategy_engine'].SymbolEngine, 'run', dummy_run)
    engine = HybridStrategyEngine('BTCUSDT', 'ETHUSDT')
    engine.ref_price = 1.0
    await engine.run()
    assert engine.mm_active
    assert engine.stat_arb_active

@pytest.mark.asyncio
async def test_mm_disabled(monkeypatch):
    trading.enable_mm = False
    trading.enable_stat_arb = False

    async def dummy_ws(*args, **kwargs):
        return None

    monkeypatch.setattr(sys.modules['app.exchange'].BybitClient, 'ws_multi', dummy_ws)
    async def dummy_run(self):
        return
    monkeypatch.setattr(sys.modules['app.hybrid_strategy_engine'].SymbolEngine, 'run', dummy_run)
    engine = HybridStrategyEngine('BTCUSDT', 'ETHUSDT')
    engine.ref_price = 1.0
    await engine.run()
    assert not engine.mm_active
    assert not engine.stat_arb_active


def test_open_position_filters(monkeypatch):
    trading.enable_mom_filter = True
    trading.use_ml_scoring = True
    engine = HybridStrategyEngine("BTCUSDT")
    engine.market.price_window.extend([100, 99, 98, 97, 96])
    called = False

    async def dummy_open(self, direction, price, reason=None, filters=None, features=None):
        nonlocal called
        called = True

    monkeypatch.setattr(SymbolEngine, "_open_position", dummy_open)
    monkeypatch.setattr(engine, "_ml_evaluate_signal", lambda feats: False)

    asyncio.run(engine._open_position("LONG", 100))
    assert not called
