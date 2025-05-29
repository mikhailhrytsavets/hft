# app/exchange.py

import asyncio
import json
import inspect
import logging
import websockets
from pybit.unified_trading import HTTP
from pybit.exceptions import InvalidRequestError
import time
import math
import requests
from utils.retry import async_retry_rest
import urllib3

logger = logging.getLogger(__name__)

class BybitClient:
    def __init__(
        self,
        symbol: str,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        demo: bool = False,
        channel_type: str = "linear",
        place_orders: bool = True,
    ):
        self.symbol = symbol
        self.channel_type = channel_type
        self.demo = demo
        self.place_orders = place_orders
        self._init_http(api_key, api_secret, testnet, demo)

    def _init_http(self, key, secret, testnet, demo):
        self.http = HTTP(
            api_key=key, api_secret=secret,
            testnet=testnet, demo=demo,
            timeout=30, recv_window=30000
        )

    def refresh_http(self):
        logger.info(f"[{self.symbol}] 🔄 Refreshing HTTP session…")
        self._init_http(self.http.api_key, self.http.api_secret, self.http.testnet, self.http.demo)

    def gen_link_id(self, tag: str) -> str:
        """Return a unique orderLinkId for idempotent orders."""
        ts = int(time.time() * 1000)
        return f"{self.symbol}-{tag}-{ts}"

    @async_retry_rest()
    async def place_order(self, **params):
        if not self.place_orders:
            logger.warning(f"[{self.symbol}] 🚫 place_order suppressed: {params}")
            return {}
        try:
            return await asyncio.to_thread(self.http.place_order, **params)
        except InvalidRequestError as e:
            # 110030 – Duplicate orderId (idempotent retry)
            if "110030" in str(e):
                logger.info(f"[{self.symbol}] ℹ️ Duplicate order ignored")
                return {}
            raise
        except (requests.ConnectionError, urllib3.exceptions.ProtocolError):
            self.refresh_http()
            raise

    @async_retry_rest()
    async def cancel_order(self, **params):
        if not self.place_orders:
            logger.warning(f"[{self.symbol}] 🚫 cancel_order suppressed: {params}")
            return {}
        return await asyncio.to_thread(self.http.cancel_order, **params)

    @async_retry_rest()
    async def get_wallet_balance(self, **params):
        return await asyncio.to_thread(self.http.get_wallet_balance, **params)

    @async_retry_rest()
    async def get_open_orders(self, **params):
        return await asyncio.to_thread(self.http.get_open_orders, **params)

    async def price_stream(self, timeout: float = 30.0):
        """Yield prices with auto‑reconnect on errors."""
        url = "wss://stream.bybit.com/v5/public/linear"
        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    url, ping_interval=20, close_timeout=10, max_queue=None
                ) as ws:
                    sub = {"op": "subscribe", "args": [f"publicTrade.{self.symbol}"]}
                    await ws.send(json.dumps(sub))
                    logger.info(f"[{self.symbol}] ✅ Подписка на publicTrade")
                    attempt = 0
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout)
                        except asyncio.TimeoutError:
                            raise ConnectionError("WS recv timeout")
                        msg = json.loads(raw)
                        data = msg.get("data")
                        if data and isinstance(data, list):
                            yield float(data[0]["p"])
            except Exception as e:
                attempt += 1
                wait = min(2 ** attempt, 64)
                logger.warning(f"❌ [WS] Поток цен {self.symbol} закрылся: {type(e).__name__} → {e}. Повтор через {wait}s")
                await asyncio.sleep(wait)

    async def create_market_order(self, side: str, qty: float):
        """Place a market order with a unique ``orderLinkId``."""
        if not self.place_orders:
            logger.warning(f"[{self.symbol}] 🚫 create_market_order suppressed: {side} {qty}")
            return {}
        from pybit.exceptions import InvalidRequestError
        link_id = self.gen_link_id("mk")
        while qty > 0:
            try:
                return await self.place_order(
                    category="linear",
                    symbol=self.symbol,
                    side=side,
                    orderType="Market",
                    qty=qty,
                    reduceOnly=False,
                    orderLinkId=link_id,
                )
            except InvalidRequestError as e:
                if "max. limit" in str(e):
                    qty = math.floor(qty * 0.8)
                    logger.info(f"[{self.symbol}] 🔄 qty↓ → {qty}")
                    continue
                raise

    async def create_reduce_only_sl(
        self,
        side: str,
        qty: float,
        trigger_price: float,
        position_idx: int = 0,
        order_link_id: str | None = None,
    ):
        """
        Биржевой стоп-маркет reduce-only (реальный SL на бирже).
        side — сторона исходной позиции ("Buy" → ставим "Sell" стоп).
        """
        if not self.place_orders:
            logger.warning(
                f"[{self.symbol}] 🚫 create_reduce_only_sl suppressed: {side} {qty} @{trigger_price}"
            )
            return {}
        category = "linear" if self.symbol.endswith("USDT") else "inverse"
        trigger_direction = 2 if side == "Buy" else 1
        params = dict(
            category=category,
            symbol=self.symbol,
            side="Sell" if side == "Buy" else "Buy",
            orderType="Market",
            qty=qty,
            triggerPrice=trigger_price,
            triggerDirection=trigger_direction,
            reduceOnly=True,
            positionIdx=position_idx,
            timeInForce="IOC",
        )
        if order_link_id:
            params["orderLinkId"] = order_link_id
        return await self.place_order(**params)

    def set_leverage(self, symbol: str, leverage: int) -> None:
        if not self.place_orders:
            logger.warning(f"[{symbol}] 🚫 set_leverage suppressed")
            return
        category = "linear" if symbol.endswith("USDT") else "inverse"
        try:
            self.http.set_leverage(
                category=category,
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            logger.info(f"[{symbol}] ⚙️ Leverage set to {leverage}x")
        except InvalidRequestError as err:
            # 110043 -> уже такое же плечо
            if "110043" in str(err):
                logger.info(f"[{symbol}] ℹ️ Leverage already {leverage}x – пропускаем")
            else:
                raise  # всё остальное пробрасываем наружу

    async def get_position(self):
        """Возвращает первую запись позиции по символу."""
        category = "linear" if self.symbol.endswith("USDT") else "inverse"
        data = await asyncio.to_thread(
            self.http.get_positions, category=category, symbol=self.symbol
        )
        return data["result"]["list"][0] if data.get("result", {}).get("list") else {}

    def subscribe_orderbook(self, handler):
        """
        Подписка на стакан через общий WS‑хелпер (без threading).
        `handler(data)` — старый колбэк, где data = orderbook snapshot/update.
        """
        loop = asyncio.get_event_loop()

        def ob_handler(sym: str, data):
            handler(data)

        loop.create_task(BybitClient.ws_multi([self.symbol], "orderbook.50", ob_handler))

    def subscribe_trades(self, handler):
        """
        Подписка на трейды через общий WS‑хелпер (без threading).
        `handler(data)` — старый колбэк, где data = список трейдов.
        """
        loop = asyncio.get_event_loop()

        def trades_handler(sym: str, data):
            handler(data)

        loop.create_task(BybitClient.ws_multi([self.symbol], "publicTrade", trades_handler))

    # ---------- shared WebSocket ----------
    @staticmethod
    async def ws_multi(symbols: list[str], channel: str, handler):
        """Subscribe to ``channel`` for multiple symbols with auto-reconnect."""
        url = "wss://stream.bybit.com/v5/public/linear"
        topics = [f"{channel}.{s}" for s in symbols]
        attempt = 0
        while True:
            try:
                async with websockets.connect(
                    url, ping_interval=20, close_timeout=10, max_queue=None
                ) as ws:
                    await ws.send(json.dumps({"op": "subscribe", "args": topics}))
                    attempt = 0
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if "topic" not in data or "data" not in data:
                            continue
                        topic = data["topic"]  # e.g. orderbook.50.XRPUSDT
                        sym = topic.split(".")[-1]
                        result = handler(sym, data["data"])
                        if inspect.isawaitable(result):
                            await result
            except Exception as e:
                attempt += 1
                wait = min(2 ** attempt, 64)
                logger.warning(f"❌ [WS] multi-stream closed: {type(e).__name__} → {e}. Retry in {wait}s")
                await asyncio.sleep(wait)

    async def get_orderbook(self):
        """Возвращает топ стакана (best bid/ask)."""
        category = "linear"
        data = await asyncio.to_thread(
            self.http.get_orderbook, category=category, symbol=self.symbol, limit=1
        )
        return data["result"]

    async def max_position_size(self, price: float, leverage: int) -> float | None:
        """
        Возвращает максимальный size (контракты) по текущему плече.
        Для linear-перпетуалов лимит в USD (riskLimitValue), делим на price и умножаем на leverage.
        """
        try:
            risk = await asyncio.to_thread(
                self.http.get_risk_limit, category="linear", symbol=self.symbol
            )
            level = risk["result"]["list"][0]
            usd_limit = float(level["riskLimitValue"])
            return usd_limit / price * leverage
        except Exception as e:
            logger.warning(f"[{self.symbol}] ⚠️ Не смог получить risk-limit: {e}")
            return None

    @async_retry_rest()
    async def get_klines(self, symbol: str, interval: str, limit: int = 200):
        """Return kline/candlestick data."""
        data = await asyncio.to_thread(
            self.http.get_kline,
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
        return data.get("result", {}).get("list", [])

