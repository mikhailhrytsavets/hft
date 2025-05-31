import asyncio
import aiohttp
from pathlib import Path
from app.config import settings
from app.notifier import notify_telegram

OFFSET_FILE = Path(__file__).parent.parent / "telegram_offset.txt"

async def telegram_command_listener():
    try:
        offset = int(OFFSET_FILE.read_text())
    except Exception:
        offset = 0
    token = settings.telegram.bot_token
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params={"timeout": 100, "offset": offset}) as resp:
                    data = await resp.json()
        except Exception as e:
            print(f"Telegram poll error: {e}")
            await asyncio.sleep(5)
            continue
        for upd in data.get("result", []):
            offset = upd["update_id"] + 1
            try:
                OFFSET_FILE.write_text(str(offset))
            except Exception:
                pass
            text = upd.get("message", {}).get("text", "")
            if not text.startswith("/set"):
                continue
            parts = text.split()
            if len(parts) != 4:
                continue
            _, symbol, key, value = parts
            try:
                val = float(value)
                if hasattr(settings.trading, key):
                    setattr(settings.trading, key, val)
                    await notify_telegram(f"{key} set to {val}")
                else:
                    await notify_telegram(f"unknown key: {key}")
            except Exception as exc:
                await notify_telegram(f"cmd error: {exc}")
        await asyncio.sleep(1)

