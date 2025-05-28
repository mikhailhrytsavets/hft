# Example WebSocket client

import asyncio
import json
import websockets

async def main():
    url = "wss://stream.bybit.com/v5/public/linear"
    async with websockets.connect(url, ping_interval=20) as ws:
        sub = {
            "op": "subscribe",
            "args": ["orderbook.50.XRPUSDT"]
        }
        await ws.send(json.dumps(sub))
        print("✅ Подписан на стакан")
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            print("📥", data)

if __name__ == "__main__":
    asyncio.run(main())
