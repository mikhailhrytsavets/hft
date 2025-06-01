from app.market_features import FeatureCollector

class SignalEngine:
    def __init__(self, z_threshold=1.2):
        self.features = FeatureCollector()
        self.z_threshold = z_threshold

    def update(self, price: float, volume: float):
        self.features.update(price, volume)

    def check_signal(self):
        z = self.features.zscore()
        if z > self.z_threshold:
            return "SHORT"
        elif z < -self.z_threshold:
            return "LONG"
        else:
            return None
