from __future__ import annotations

"""Market micro-structure features used by strategies."""

from collections import deque
import statistics
import math
import collections

from app.core.data import Bar


class FeatureCollector:
    def __init__(self, maxlen: int = 100) -> None:
        self.prices = collections.deque(maxlen=maxlen)
        self.volumes = collections.deque(maxlen=maxlen)

    def update(self, price: float, volume: float = 1.0) -> None:
        self.prices.append(price)
        self.volumes.append(volume)

    def vwap(self) -> float:
        if not self.prices or not self.volumes:
            return 0.0
        total = sum(self.volumes)
        if total == 0:
            return 0.0
        return sum(p * v for p, v in zip(self.prices, self.volumes)) / total

    def zscore(self, window: int = 30) -> float:
        if len(self.prices) < window:
            return 0.0
        window_prices = list(self.prices)[-window:]
        mean = statistics.mean(window_prices)
        stdev = statistics.stdev(window_prices)
        if stdev == 0:
            return 0.0
        return (self.prices[-1] - mean) / stdev


class MarketFeatures:
    """Compute rolling order-book and trade flow metrics."""

    def __init__(self, depth_levels: int = 5, window: int = 20) -> None:
        self.depth_levels = depth_levels
        # live values updated from orderbook/trade streams
        self.latest_obi: float = 0.0
        self.latest_vbd: float = 0.0
        self.latest_spread: float = 0.0
        self.latest_spread_z: float = 0.0
        self.latest_volatility: float = 0.0
        # rolling per-bar series
        self._obis: deque[float] = deque(maxlen=window)
        self._vbds: deque[float] = deque(maxlen=window)
        self._spreads: deque[float] = deque(maxlen=window)
        self._returns: deque[float] = deque(maxlen=window)
        # tick-level series
        self.price_window: deque[float] = deque(maxlen=window)
        self._tick_returns: deque[float] = deque(maxlen=window)
        # aggregated metrics
        self.obi: float = 0.0
        self.vbd: float = 0.0
        self.spread_z: float = 0.0
        self.volatility: float = 0.0
        self._last_close: float | None = None

    # ------------------------------------------------------------------
    def compute_obi(self, bids: list, asks: list) -> float:
        """Update and return order book imbalance."""
        bid_vol = sum(float(b[1]) for b in bids[: self.depth_levels])
        ask_vol = sum(float(a[1]) for a in asks[: self.depth_levels])
        total = bid_vol + ask_vol
        self.latest_obi = (bid_vol - ask_vol) / total if total else 0.0
        return self.latest_obi

    def update_vbd(self, buy_vol: float, sell_vol: float) -> float:
        total = buy_vol + sell_vol
        self.latest_vbd = (buy_vol - sell_vol) / total if total else 0.0
        return self.latest_vbd

    def update_spread(self, best_bid: float, best_ask: float) -> float:
        spread = best_ask - best_bid
        self.latest_spread = spread
        self._spreads.append(spread)
        if len(self._spreads) < 2:
            self.latest_spread_z = 0.0
        else:
            mean = statistics.mean(self._spreads)
            stdev = statistics.stdev(self._spreads)
            self.latest_spread_z = 0.0 if stdev == 0 else (spread - mean) / stdev
        return self.latest_spread_z

    def update_volatility(self, price: float) -> float:
        """Update intra-bar volatility estimate using tick prices."""
        if self.price_window:
            last_price = self.price_window[-1]
            if last_price > 0 and price > 0:
                ret = math.log(price / last_price)
                self._tick_returns.append(ret)
        self.price_window.append(price)
        if len(self._tick_returns) > 1:
            self.latest_volatility = statistics.stdev(self._tick_returns)
        else:
            self.latest_volatility = 0.0
        return self.latest_volatility

    async def on_bar(self, bar: Bar) -> None:
        if self._last_close is not None and bar.close > 0:
            ret = math.log(bar.close / self._last_close)
            self._returns.append(ret)
        self._last_close = bar.close
        self._obis.append(self.latest_obi)
        self._vbds.append(self.latest_vbd)
        # store spread to compute z-score of spreads across bars
        self._spreads.append(self.latest_spread)
        self.obi = statistics.mean(self._obis)
        self.vbd = statistics.mean(self._vbds)
        if len(self._returns) > 1:
            self.volatility = statistics.stdev(self._returns)
        else:
            self.volatility = 0.0
        if len(self._spreads) > 1:
            mean = statistics.mean(self._spreads)
            stdev = statistics.stdev(self._spreads)
            self.spread_z = 0.0 if stdev == 0 else (self._spreads[-1] - mean) / stdev
        else:
            self.spread_z = 0.0

    def snapshot(self) -> dict[str, float]:
        return {
            "obi": round(self.obi, 6),
            "vbd": round(self.vbd, 6),
            "spread_z": round(self.spread_z, 6),
            "volatility": round(self.volatility, 6),
        }

    def update_taker_flow(self, buy_vol: float, sell_vol: float) -> float:
        total = buy_vol + sell_vol
        if total == 0:
            return 0.0
        tflow = (buy_vol - sell_vol) / total
        if not hasattr(self, "taker_window"):
            self.taker_window = deque(maxlen=20)
        self.taker_window.append(tflow)
        return sum(self.taker_window) / len(self.taker_window)


def compute_features(
    collector: FeatureCollector,
    market: MarketFeatures,
    price: float,
    bids: list,
    asks: list,
    buy_vol: float,
    sell_vol: float,
) -> tuple[float, float, float, float, float]:
    """Update helpers and return z, vbd, spread_z, tflow, vol."""

    collector.update(price, buy_vol + sell_vol)
    z = collector.zscore()

    market.compute_obi(bids, asks)
    vbd = market.update_vbd(buy_vol, sell_vol)
    spread_z = market.update_spread(float(bids[0][0]), float(asks[0][0]))
    tflow = market.update_taker_flow(buy_vol, sell_vol)
    vol = market.update_volatility(price)
    return z, vbd, spread_z, tflow, vol

