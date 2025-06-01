import types
import sys
import asyncio
import importlib


def setup_engine(monkeypatch):
    trading = types.SimpleNamespace(
        leverage=1,
        enable_hedging=False,
        candle_interval_sec=1,
        rsi_period=14,
        adx_period=14,
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
            self.http = types.SimpleNamespace()
        def set_leverage(self, *a, **k):
            pass

        async def cancel_order(self, *a, **k):
            pass

        async def create_reduce_only_sl(self, side, qty, trigger_price, order_link_id=None, position_idx=0):
            return {"result": {"orderId": "42"}}

        def gen_link_id(self, tag):
            return "id"

    monkeypatch.setitem(sys.modules, 'app.exchange', types.SimpleNamespace(BybitClient=DummyClient))

    import app.symbol_engine as se
    importlib.reload(se)
    se.settings = settings_stub
    engine = se.SymbolEngine("ADAUSDT")
    engine.precision.step = lambda http, symbol: 0.1
    return engine


def test_set_sl_rechecks_price(monkeypatch):
    engine = setup_engine(monkeypatch)
    engine.risk.position.side = "Buy"
    engine.risk.position.qty = 1.0
    engine.close_window.append(1.0)
    engine.sl_order_id = "old"

    prices = [1.0, 0.95]

    async def cancel_order(*a, **k):
        engine.close_window.append(prices[1])

    captured = {}

    async def create_sl(side, qty, trigger_price, order_link_id=None, position_idx=0):
        captured['price'] = trigger_price
        return {"result": {"orderId": "99"}}

    monkeypatch.setattr(engine.client, 'cancel_order', cancel_order)
    monkeypatch.setattr(engine.client, 'create_reduce_only_sl', create_sl)
    monkeypatch.setattr(engine.client, 'gen_link_id', lambda tag: 'id')

    asyncio.run(engine._set_sl(1.0, 1.1, prices[0]))

    assert captured['price'] < prices[1]
    assert engine.sl_order_id == "99"
    assert engine.current_sl_price == captured['price']

