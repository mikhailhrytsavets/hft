from collections import deque
import math
import statistics

class MarketFeatures:
    def __init__(self, depth_levels: int = 5) -> None:
        self.depth_levels = depth_levels
        # tick level buffers
        self.vol_deltas = deque(maxlen=20)
        self.spreads_tick = deque(maxlen=20)
        self.price_window = deque(maxlen=30)
        self.last_vol = 0.0

        # rolling bar metrics -------------------------------------------------
        self.obi_hist = deque(maxlen=20)
        self.vbd_hist = deque(maxlen=20)
        self.spread_hist = deque(maxlen=20)
        self.ret_hist = deque(maxlen=20)

        self._obi_sum = 0.0
        self._vbd_sum = 0.0
        self._spread_sum = 0.0
        self._spread_sq_sum = 0.0
        self._ret_sum = 0.0
        self._ret_sq_sum = 0.0
        self._prev_close: float | None = None

        self.latest_obi: float = 0.0
        self.latest_vbd: float = 0.0
        self.latest_spread: float = 0.0

    def compute_obi(self, bids: list, asks: list) -> float:
        bid_vol = sum([float(b[1]) for b in bids[:self.depth_levels]])
        ask_vol = sum([float(a[1]) for a in asks[:self.depth_levels]])
        total = bid_vol + ask_vol
        self.latest_obi = (bid_vol - ask_vol) / total if total else 0.0
        return self.latest_obi

    def update_vbd(self, buy_vol: float, sell_vol: float) -> float:
        delta = buy_vol - sell_vol
        self.vol_deltas.append(delta)
        total = sum(abs(d) for d in self.vol_deltas)
        self.latest_vbd = sum(self.vol_deltas) / total if total else 0.0
        return self.latest_vbd

    def update_spread(self, best_bid: float, best_ask: float) -> float:
        spread = best_ask - best_bid
        self.spreads_tick.append(spread)
        self.latest_spread = spread
        if len(self.spreads_tick) < 2:
            return 0.0
        mean = statistics.mean(self.spreads_tick)
        stdev = statistics.stdev(self.spreads_tick)
        if stdev == 0:
            return 0.0
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

    # ------------------------------------------------------------------
    async def on_bar(self, bar) -> None:
        """Update rolling metrics when a 5m bar completes."""
        if self._prev_close is not None and bar.close > 0:
            ret = math.log(bar.close / self._prev_close)
            if len(self.ret_hist) == self.ret_hist.maxlen:
                old = self.ret_hist.popleft()
                self._ret_sum -= old
                self._ret_sq_sum -= old * old
            self.ret_hist.append(ret)
            self._ret_sum += ret
            self._ret_sq_sum += ret * ret
        self._prev_close = bar.close

        self._append_metric(self.obi_hist, bar=bar, value=self.latest_obi,
                            sum_attr="_obi_sum")
        self._append_metric(self.vbd_hist, bar=bar, value=self.latest_vbd,
                            sum_attr="_vbd_sum")
        self._append_metric(self.spread_hist, bar=bar, value=self.latest_spread,
                            sum_attr="_spread_sum", sq_attr="_spread_sq_sum")

    def _append_metric(self, dq: deque, *, bar, value: float,
                       sum_attr: str, sq_attr: str | None = None) -> None:
        if len(dq) == dq.maxlen:
            old = dq.popleft()
            setattr(self, sum_attr, getattr(self, sum_attr) - old)
            if sq_attr:
                setattr(self, sq_attr, getattr(self, sq_attr) - old * old)
        dq.append(value)
        setattr(self, sum_attr, getattr(self, sum_attr) + value)
        if sq_attr:
            setattr(self, sq_attr, getattr(self, sq_attr) + value * value)

    def snapshot(self) -> dict[str, float]:
        def mean(sum_val, length):
            return sum_val / length if length else 0.0

        res = {}
        n_obi = len(self.obi_hist)
        res["obi"] = round(mean(self._obi_sum, n_obi), 6)

        n_vbd = len(self.vbd_hist)
        res["vbd"] = round(mean(self._vbd_sum, n_vbd), 6)

        n_spread = len(self.spread_hist)
        if n_spread:
            m = self._spread_sum / n_spread
            var = self._spread_sq_sum / n_spread - m * m
            sd = math.sqrt(var) if var > 0 else 0.0
            res["spread_z"] = round((self.spread_hist[-1] - m) / sd if sd else 0.0, 6)
        else:
            res["spread_z"] = 0.0

        n_ret = len(self.ret_hist)
        if n_ret:
            m = self._ret_sum / n_ret
            var = self._ret_sq_sum / n_ret - m * m
            sd = math.sqrt(var) if var > 0 else 0.0
            res["volatility"] = round(sd, 6)
        else:
            res["volatility"] = 0.0

        return res
