from __future__ import annotations

import asyncio
import json
import inspect
import time
import math

from pybit.exceptions import InvalidRequestError

from utils.retry import async_retry_rest

from app.http_client import HttpClient
from app.ws_client import WsClient


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
    ) -> None:
        self.symbol = symbol
        self.channel_type = channel_type
        self.place_orders = place_orders
        self.http = HttpClient(api_key, api_secret, testnet=testnet, demo=demo)

    def gen_link_id(self, tag: str) -> str:
        ts = int(time.time() * 1000)
        return f"{self.symbol}-{tag}-{ts}"

    @async_retry_rest()
    async def place_order(self, **params):
        if not self.place_orders:
            print(f"[{self.symbol}] 🚫 place_order suppressed: {params}")
            return {}
        return await self.http.create_order(**params)

    @async_retry_rest()
    async def cancel_order(self, **params):
        if not self.place_orders:
            print(f"[{self.symbol}] 🚫 cancel_order suppressed: {params}")
            return {}
        return await asyncio.to_thread(self.http.http.cancel_order, **params)

    @async_retry_rest()
    async def get_open_orders(self, **params):
        return await asyncio.to_thread(self.http.http.get_open_orders, **params)

    @async_retry_rest()
    async def get_wallet_balance(self, **params):
        return await self.http.get_wallet_balance(**params)

    async def create_market_order(self, side: str, qty: float, reduce_only: bool = False):
        link_id = self.gen_link_id("mk")
        while qty > 0:
            try:
                return await self.place_order(
                    category="linear",
                    symbol=self.symbol,
                    side=side,
                    orderType="Market",
                    qty=qty,
                    reduceOnly=reduce_only,
                    timeInForce="IOC",
                    orderLinkId=link_id,
                )
            except InvalidRequestError as e:
                if "max. limit" in str(e):
                    qty = math.floor(qty * 0.8)
                    continue
                raise

    async def create_limit_order(self, side: str, qty: float, price: float, reduce_only: bool = False):
        link_id = self.gen_link_id("lmt")
        while qty > 0:
            try:
                return await self.place_order(
                    category="linear",
                    symbol=self.symbol,
                    side=side,
                    orderType="Limit",
                    qty=qty,
                    price=price,
                    timeInForce="GTC",
                    reduceOnly=reduce_only,
                    orderLinkId=link_id,
                )
            except InvalidRequestError as e:
                if "max. limit" in str(e):
                    qty = math.floor(qty * 0.8)
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
        params = dict(
            category="linear",
            symbol=self.symbol,
            side="Sell" if side == "Buy" else "Buy",
            orderType="Market",
            qty=qty,
            triggerPrice=trigger_price,
            triggerDirection=2 if side == "Buy" else 1,
            reduceOnly=True,
            positionIdx=position_idx,
            timeInForce="IOC",
        )
        if order_link_id:
            params["orderLinkId"] = order_link_id
        return await self.place_order(**params)

    def set_leverage(self, symbol: str, leverage: int) -> None:
        try:
            self.http.http.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
        except InvalidRequestError as err:
            if "110043" in str(err):
                return
            raise

    async def get_position(self):
        data = await asyncio.to_thread(
            self.http.http.get_positions, category="linear", symbol=self.symbol
        )
        return data["result"]["list"][0] if data.get("result", {}).get("list") else {}

    @staticmethod
    async def ws_multi(symbols: list[str], channel: str, handler):
        await WsClient.ws_multi(symbols, channel, handler)
