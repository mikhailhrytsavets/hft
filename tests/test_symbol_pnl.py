import types
import sys
import asyncio
import importlib
import pytest

def test_multiple_tp1_pnl_accumulates(monkeypatch):
    trading = types.SimpleNamespace(
        leverage=1,
        enable_hedging=False,
        candle_interval_sec=1,
        rsi_period=14,
        adx_period=14,
        tp1_close_ratio=0.5,
        tp2_close_ratio=0.5,
        min_profit_to_be=0.0,
    )
    entry_score = types.SimpleNamespace(symbol_weights={}, weights={}, threshold_k=1.0, symbol_threshold_k={})
    settings_stub = types.SimpleNamespace(
        bybit=types.SimpleNamespace(api_key="", api_secret="", testnet=False, demo=False, place_orders=False, channel_type="linear"),
        trading=trading,
        risk=types.SimpleNamespace(max_open_positions=0),
        telegram=None,
        entry_score=entry_score,
        multi_tf=types.SimpleNamespace(enable=False, intervals=[]),
        symbol_params={},
    )
    monkeypatch.setitem(sys.modules, 'app.config', types.SimpleNamespace(settings=settings_stub, SymbolParams=types.SimpleNamespace))

    class DummyClient:
        def __init__(self, symbol, *a, **k):
            self.symbol = symbol
            self.place_orders = False
            self.http = types.SimpleNamespace(
                get_positions=lambda category, symbol: {"result": {"list": [{}]}},
                get_open_orders=lambda category, symbol: {"result": {"list": []}},
            )
        def set_leverage(self, *a, **k):
            pass
        async def create_market_order(self, *a, **k):
            return {"result": {"orderId": "1"}}
        async def get_open_orders(self, *a, **k):
            return {"result": {"list": []}}
        def gen_link_id(self, tag):
            return "id"

    monkeypatch.setitem(sys.modules, 'app.exchange', types.SimpleNamespace(BybitClient=DummyClient))

    import app.symbol_engine as se
    importlib.reload(se)
    se.settings = settings_stub

    engine = se.SymbolEngine("BTCUSDT")
    engine.precision.step = lambda http, symbol: 0.1
    engine.risk.position.side = "Buy"
    engine.risk.position.qty = 1.0
    engine.risk.position.avg_price = 100.0
    engine.risk.entry_value = 100.0
    engine.last_pnl_id = "1"

    calls = 0
    def fake_closed_pnl(category="linear", symbol="", limit=10):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"result": {"list": [
                {"execId": "3", "closedPnl": "1.0", "cumEntryValue": "100"},
                {"execId": "2", "closedPnl": "0.5", "cumEntryValue": "100"},
                {"execId": "1", "closedPnl": "0", "cumEntryValue": "100"},
            ]}}
        elif calls == 2:
            return {"result": {"list": [
                {"execId": "4", "closedPnl": "0.3", "cumEntryValue": "100"},
                {"execId": "3", "closedPnl": "1.0", "cumEntryValue": "100"},
                {"execId": "2", "closedPnl": "0.5", "cumEntryValue": "100"},
            ]}}
        return {"result": {"list": []}}

    engine.client.http.get_closed_pnl = fake_closed_pnl
    monkeypatch.setattr(engine, "_wait_order_fill", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(engine, "_set_sl", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(se, "notify_telegram", lambda *a, **k: asyncio.sleep(0))

    asyncio.run(engine._handle_tp1(105))
    assert engine.risk.realized_pnl == pytest.approx(1.5)
    assert engine.last_pnl_id == "3"

    asyncio.run(engine._handle_tp1(110))
    assert engine.risk.realized_pnl == pytest.approx(1.8)
    assert engine.last_pnl_id == "4"


def test_fetch_closed_pnl_waits_for_new_entry(monkeypatch):
    trading = types.SimpleNamespace(
        leverage=1,
        enable_hedging=False,
        candle_interval_sec=1,
        rsi_period=14,
        adx_period=14,
        tp1_close_ratio=0.5,
        tp2_close_ratio=0.5,
        min_profit_to_be=0.0,
    )
    entry_score = types.SimpleNamespace(symbol_weights={}, weights={}, threshold_k=1.0, symbol_threshold_k={})
    settings_stub = types.SimpleNamespace(
        bybit=types.SimpleNamespace(api_key="", api_secret="", testnet=False, demo=False, place_orders=False, channel_type="linear"),
        trading=trading,
        risk=types.SimpleNamespace(max_open_positions=0),
        telegram=None,
        entry_score=entry_score,
        multi_tf=types.SimpleNamespace(enable=False, intervals=[]),
        symbol_params={},
    )
    monkeypatch.setitem(sys.modules, 'app.config', types.SimpleNamespace(settings=settings_stub, SymbolParams=types.SimpleNamespace))

    class DummyClient:
        def __init__(self, symbol, *a, **k):
            self.symbol = symbol
            self.place_orders = False
            self.http = types.SimpleNamespace(
                get_positions=lambda category, symbol: {"result": {"list": [{}]}},
                get_open_orders=lambda category, symbol: {"result": {"list": []}},
            )
        def set_leverage(self, *a, **k):
            pass

    monkeypatch.setitem(sys.modules, 'app.exchange', types.SimpleNamespace(BybitClient=DummyClient))

    import app.symbol_engine as se
    importlib.reload(se)
    se.settings = settings_stub

    engine = se.SymbolEngine("BTCUSDT")
    engine.precision.step = lambda http, symbol: 0.1
    engine.last_pnl_id = None

    calls = 0
    def fake_closed_pnl(category="linear", symbol="", limit=10):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"result": {"list": [
                {"execId": "1", "closedPnl": "0.2", "cumEntryValue": "100"},
            ]}}
        return {"result": {"list": [
            {"execId": "2", "closedPnl": "0.3", "cumEntryValue": "100"},
            {"execId": "1", "closedPnl": "0.2", "cumEntryValue": "100"},
        ]}}

    engine.client.http.get_closed_pnl = fake_closed_pnl

    async def instant_sleep(_=0):
        pass

    monkeypatch.setattr(se.asyncio, "sleep", instant_sleep)

    pnl = asyncio.run(se._fetch_closed_pnl(engine, retries=3))
    assert pnl == (0.3, 0.3)
    assert engine.last_pnl_id == "2"
