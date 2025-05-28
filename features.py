import collections
import statistics

class FeatureCollector:
    def __init__(self, maxlen=100):
        self.prices = collections.deque(maxlen=maxlen)
        self.volumes = collections.deque(maxlen=maxlen)

    def update(self, price: float, volume: float = 1.0):
        self.prices.append(price)
        self.volumes.append(volume)

    def vwap(self):
        if not self.prices or not self.volumes:
            return 0
        total_vol = sum(self.volumes)
        if total_vol == 0:
            return 0
        return sum(p * v for p, v in zip(self.prices, self.volumes)) / total_vol

    def zscore(self, window=30):
        if len(self.prices) < window:
            return 0
        window_prices = list(self.prices)[-window:]
        mean = statistics.mean(window_prices)
        stdev = statistics.stdev(window_prices)
        if stdev == 0:
            return 0
        return (self.prices[-1] - mean) / stdev
