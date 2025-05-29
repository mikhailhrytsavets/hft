import numpy as np
import pytest
from collections import deque, namedtuple

from src.core import indicators
from src.strategy.entry import BounceEntry, EntrySignal
from src.strategy.manager import PositionManager

Bar = namedtuple("Bar", "open high low close volume start end")


@pytest.fixture
def ohlc_20():
    high = np.array([11,12,13,14,15,14,13,12,11,10,
                     11,12,13,14,15,14,13,12,11,10], dtype=float)
    low  = high - 1.5
    close= (high+low)/2
    return high, low, close


@pytest.fixture
def bar_extreme():
    # pin-bar touching lower BB, volume ×3
    return Bar(10,10.05,9.5,9.6, 300, 0,0)

# ---------- ATR ---------- #
def test_atr_known(ohlc_20):
    h,l,c = ohlc_20
    atr = indicators.atr(h,l,c,period=14)
    assert round(float(atr),4) == 1.5   # constant range → ATR == range

# ---------- ENTRY ---------- #
def test_bounce_long(bar_extreme):
    closes = deque([10]*30, maxlen=30)
    vols   = deque([100]*19+[300], maxlen=20)
    sig = BounceEntry.check(bar_extreme, vols, closes, params={})
    assert sig is EntrySignal.LONG

def test_bounce_none_due_rsi():
    closes = deque([i for i in range(60)], maxlen=60)  # trending ⇒ RSI high
    bar    = Bar(59,60,58,59.9,150,0,0)
    sig = BounceEntry.check(bar, deque([120]*20), closes, {})
    assert sig is None

# ---------- MANAGER ---------- #
def test_tp1_hit():
    pm = PositionManager()
    pm.open(side="LONG", qty=1, entry=100, atr=2)      # SL 1.5 ATR, TP1 1 ATR
    assert pm.tp1 == 102
    pm.on_tick(price=102.1)
    assert pm.closed_qty == pytest.approx(0.4, rel=1e-2)
    assert pm.trailing_started

def test_tp2_and_trailing():
    pm = PositionManager()
    pm.open(side="LONG", qty=1, entry=100, atr=2)
    pm.on_tick(102.1)  # TP1
    pm.on_tick(104.1)  # TP2
    assert pm.closed_qty == pytest.approx(0.7, rel=1e-2)
    pm.on_tick(105.0)  # move best price
    trail = pm.trail_price
    assert trail and trail > 0
    pm.on_tick(trail - 0.01)
    assert pm.state.qty == 0
