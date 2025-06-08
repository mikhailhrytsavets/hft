import aiohttp
import asyncio
import logging
import re
from app.config import settings

_session: aiohttp.ClientSession | None = None
_tg_queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
_queue_loop: asyncio.AbstractEventLoop | None = None
_worker_task: asyncio.Task | None = None
logger = logging.getLogger(__name__)

async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session

async def close_session() -> None:
    global _session, _worker_task
    if _worker_task is not None:
        await _tg_queue.join()
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    if _session is not None and not _session.closed:
        await _session.close()

async def _send_telegram(msg: str, max_retries: int) -> None:
    try:
        bot_token = settings.telegram.bot_token
        chat_id = settings.telegram.chat_id
        min_interval = getattr(settings.telegram, "min_interval", 1.0)
    except AttributeError:
        logger.warning("Telegram settings not configured; message skipped")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}

    backoff = 1.0
    for attempt in range(max_retries):
        try:
            session = await _get_session()
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok"):
                        logger.info("\u2705 Telegram message sent: %s...", msg[:50])
                        await asyncio.sleep(min_interval)
                        return
                    desc = result.get("description", "")
                    if "Too Many Requests" in desc:
                        match = re.search(r"retry after (\d+)", desc)
                        if match:
                            wait = int(match.group(1))
                            logger.warning("Rate limited. Retry after %s s", wait)
                            await asyncio.sleep(wait)
                            continue
                        logger.warning("Rate limited without retry_after")
                else:
                    logger.warning("Telegram HTTP error: %s", response.status)
                    if response.status == 429:
                        data = await response.json()
                        wait = data.get("parameters", {}).get("retry_after")
                        if wait:
                            logger.warning("Retry after %s s", wait)
                            await asyncio.sleep(float(wait))
                            continue
        except asyncio.TimeoutError:
            logger.warning(
                "\u26A0\uFE0F Telegram timeout (attempt %s/%s)", attempt + 1, max_retries
            )
        except Exception as e:
            logger.warning(
                "\u274C Telegram error (attempt %s/%s): %s", attempt + 1, max_retries, e
            )

        await asyncio.sleep(backoff)
        backoff *= 2

    await asyncio.sleep(min_interval)


async def _ensure_worker() -> None:
    global _worker_task, _tg_queue, _queue_loop
    loop = asyncio.get_running_loop()
    if _queue_loop is not loop:
        _tg_queue = asyncio.Queue()
        _queue_loop = loop
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_tg_worker())


async def _tg_worker() -> None:
    while True:
        msg, retries = await _tg_queue.get()
        try:
            await _send_telegram(msg, retries)
        finally:
            _tg_queue.task_done()

async def notify_telegram(msg: str, max_retries: int = 3) -> None:
    """Queue a message to send via Telegram."""
    await _ensure_worker()
    await _tg_queue.put((msg, max_retries))

def notify_telegram_bg(msg: str) -> None:
    """Queue Telegram message from synchronous code."""
    asyncio.create_task(notify_telegram(msg))
