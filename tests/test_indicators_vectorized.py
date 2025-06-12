import time

import pytest
from core.indicators_vectorized import atr, compute_adx, compute_rsi

np = pytest.importorskip("numpy")


# --- tiny Python reference versions (for correctness check) --------------------


def _rsi_loop(prices: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full_like(prices, np.nan, dtype=float)
    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
        if i >= period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            rs = (avg_gain / avg_loss) if avg_loss else np.inf
            out[i] = 100 - 100 / (1 + rs)
    return out


def _atr_loop(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full_like(close, np.nan, dtype=float)
    for i in range(1, len(close)):
        tr = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        out[i] = tr
    # simple rolling mean
    for i in range(period, len(out)):
        out[i] = np.mean(out[i - period + 1 : i + 1])
    return out


def _adx_loop(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full_like(close, np.nan, dtype=float)
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, len(high)):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm.append(max(up_move, 0.0) if up_move > down_move else 0.0)
        minus_dm.append(max(down_move, 0.0) if down_move > up_move else 0.0)
        tr.append(
            max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        )
        if i >= period:
            tr_n = sum(tr[-period:])
            pdi = 100 * sum(plus_dm[-period:]) / tr_n
            mdi = 100 * sum(minus_dm[-period:]) / tr_n
            dx = 100 * abs(pdi - mdi) / (pdi + mdi)
            if i >= 2 * period - 1:
                adx_val = (
                    (out[i - 1] * (period - 1) + dx) / period
                    if not np.isnan(out[i - 1])
                    else dx
                )
                out[i] = adx_val
            else:
                out[i] = dx
    return out


# -------------------------------------------------------------------------------


@pytest.mark.parametrize("length", [300])
def test_vectorised_matches_loop(length: int, rng_seed: int = 42) -> None:
    rng = np.random.default_rng(rng_seed)
    prices = rng.lognormal(mean=0, sigma=0.01, size=length).cumsum()
    high = prices * (1 + rng.uniform(0, 0.001, size=length))
    low = prices * (1 - rng.uniform(0, 0.001, size=length))
    close = prices

    assert np.allclose(
        compute_rsi(prices), _rsi_loop(prices), rtol=1e-5, equal_nan=True
    )
    assert np.allclose(
        atr(high, low, close), _atr_loop(high, low, close), rtol=1e-5, equal_nan=True
    )
    assert np.allclose(
        compute_adx(high, low, close),
        _adx_loop(high, low, close),
        rtol=1e-5,
        equal_nan=True,
    )


def test_speed_benchmark() -> None:
    """Vector version should be 20× faster on 1e5 rows."""
    rng = np.random.default_rng(0)
    n = 100_000
    prices = rng.random(n).cumsum()
    high = prices + rng.random(n) * 0.005
    low = prices - rng.random(n) * 0.005
    close = prices

    t0 = time.perf_counter()
    compute_rsi(prices)
    compute_adx(high, low, close)
    atr(high, low, close)
    vec_time = time.perf_counter() - t0

    # crude loop timing (we do just one of them for fairness)
    t1 = time.perf_counter()
    _rsi_loop(prices)
    loop_time = time.perf_counter() - t1

    assert vec_time * 20 < loop_time, f"Vectorised={vec_time:.4f}s  Loop={loop_time:.4f}s"

# Tests rely only on pytest and plain Python — no extra plugins.
