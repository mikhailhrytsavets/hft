from collections import deque
import statistics

class MarketFeatures:
    def __init__(self, depth_levels=5, vol_window=10, spread_window=10):
        self.depth_levels = depth_levels
        self.vol_deltas = deque(maxlen=vol_window)
        self.spreads = deque(maxlen=spread_window)
        self.price_window = deque(maxlen=30)
        self.last_vol = 0.0

    def compute_obi(self, bids: list, asks: list) -> float:
        bid_vol = sum([float(b[1]) for b in bids[:self.depth_levels]])
        ask_vol = sum([float(a[1]) for a in asks[:self.depth_levels]])
        total = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total if total else 0

    def update_vbd(self, buy_vol: float, sell_vol: float) -> float:
        delta = buy_vol - sell_vol
        self.vol_deltas.append(delta)
        total = sum(abs(d) for d in self.vol_deltas)
        return sum(self.vol_deltas) / total if total else 0

    def update_spread(self, best_bid: float, best_ask: float) -> float:
        spread = best_ask - best_bid
        self.spreads.append(spread)
        if len(self.spreads) < 2:
            return 0
        mean = statistics.mean(self.spreads)
        stdev = statistics.stdev(self.spreads)
        if stdev == 0:
            return 0
        return (spread - mean) / stdev

    def update_volatility(self, price: float) -> float:
        """
        Скользящее стандартное отклонение цены (волатильность).
        """
        self.price_window.append(price)
        if len(self.price_window) < 5:
            self.last_vol = 0.0
            return 0.0
        import numpy as np
        self.last_vol = float(np.std(self.price_window))
        return self.last_vol

    def update_taker_flow(self, buy_vol: float, sell_vol: float) -> float:
        """
        Импульс маркет-трейдов: (BuyVol - SellVol) / Total.
        Усредняем по скользящему окну.
        """
        total = buy_vol + sell_vol
        if total == 0:
            return 0.0
        tflow = (buy_vol - sell_vol) / total
        if not hasattr(self, "taker_window"):
            from collections import deque
            self.taker_window = deque(maxlen=20)
        self.taker_window.append(tflow)
        return sum(self.taker_window) / len(self.taker_window)
