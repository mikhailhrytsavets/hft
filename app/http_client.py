from __future__ import annotations

import asyncio
from pybit.unified_trading import HTTP
from pybit.exceptions import InvalidRequestError
import requests
import urllib3
from utils.retry import async_retry_rest


class HttpClient:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False, demo: bool = False):
        self.http = HTTP(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
            demo=demo,
            timeout=30,
            recv_window=30000,
        )

    @async_retry_rest()
    async def get_wallet_balance(self, **params):
        return await asyncio.to_thread(self.http.get_wallet_balance, **params)

    @async_retry_rest()
    async def get_positions(self, **params):
        return await asyncio.to_thread(self.http.get_positions, **params)

    @async_retry_rest()
    async def create_order(self, **params):
        try:
            return await asyncio.to_thread(self.http.place_order, **params)
        except InvalidRequestError as e:
            if "110030" in str(e):
                return {}
            raise

    @async_retry_rest()
    async def cancel_order(self, **params):
        return await asyncio.to_thread(self.http.cancel_order, **params)

    @async_retry_rest()
    async def get_open_orders(self, **params):
        return await asyncio.to_thread(self.http.get_open_orders, **params)

    @async_retry_rest()
    async def get_closed_pnl(self, **params):
        return await asyncio.to_thread(self.http.get_closed_pnl, **params)

    @async_retry_rest()
    async def get_kline(self, **params):
        return await asyncio.to_thread(self.http.get_kline, **params)

    @async_retry_rest()
    async def get_orderbook(self, **params):
        return await asyncio.to_thread(self.http.get_orderbook, **params)

    @async_retry_rest()
    async def get_risk_limit(self, **params):
        try:
            return await asyncio.to_thread(self.http.get_risk_limit, **params)
        except (requests.ConnectionError, urllib3.exceptions.ProtocolError):
            self.http = HTTP(
                api_key=self.http.api_key,
                api_secret=self.http.api_secret,
                testnet=self.http.testnet,
                demo=self.http.demo,
                timeout=30,
                recv_window=30000,
            )
            raise
