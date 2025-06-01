from __future__ import annotations

import asyncio
import json
import websockets


class WsClient:
    @staticmethod
    async def ws_multi(symbols: list[str], channel: str, handler):
        url = "wss://stream.bybit.com/v5/public/linear"
        topics = [f"{channel}.{s}" for s in symbols]
        attempt = 0
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, close_timeout=10, max_queue=None) as ws:
                    await ws.send(json.dumps({"op": "subscribe", "args": topics}))
                    attempt = 0
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if "topic" not in data or "data" not in data:
                            continue
                        topic = data["topic"]
                        sym = topic.split(".")[-1]
                        result = handler(sym, data["data"])
                        if asyncio.iscoroutine(result):
                            await result
            except Exception as e:
                attempt += 1
                wait = min(2 ** attempt, 64)
                print(f"❌ [WS] multi-stream closed: {type(e).__name__} → {e}. Retry in {wait}s")
                await asyncio.sleep(wait)
