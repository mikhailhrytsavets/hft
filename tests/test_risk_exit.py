import types
import asyncio
from datetime import datetime, timedelta
import sys
import pytest

# minimal settings stub
trading = types.SimpleNamespace(
    hard_sl_percent=2.0,
    use_atr_stop=True,
    atr_stop_multiplier=1.5,
    break_even_after_percent=0.0,
    break_even_after_minutes=0,
    min_profit_to_be=0.0,
    enable_position_timeout=False,
    max_position_minutes=0,
    tp1_percent=0.5,
    tp2_percent=None,
    take_profit_percent=1.0,
    trailing_distance_percent=0.2,
)
settings_stub = types.SimpleNamespace(trading=trading, symbol_params={})
sys.modules['app.config'] = types.SimpleNamespace(settings=settings_stub, SymbolParams=types.SimpleNamespace)

from app.risk import RiskManager  # noqa: E402

rm = RiskManager("BTCUSDT")
rm.position.side = "Buy"
rm.position.qty = 1
rm.position.avg_price = 100.0
rm.position.open_time = datetime.utcnow() - timedelta(minutes=1)

for _ in range(20):
    rm.price_window.append((101, 99, 100))

@pytest.mark.asyncio
async def test_hard_sl_trigger():
    sig = await rm.check_exit(97)
    assert sig == "HARD_SL"

@pytest.mark.asyncio
async def test_atr_stop_trigger():
    trading.hard_sl_percent = 0.0
    sig = await rm.check_exit(96)
    assert sig == "SOFT_SL"
