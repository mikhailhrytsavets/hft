import aiohttp
import asyncio
import logging
from app.config import settings

logger = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None

async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session

async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()

async def notify_telegram(msg: str, max_retries: int = 3) -> bool:
    """
    Отправляет сообщение в Telegram с повторными попытками.
    Возвращает True если сообщение успешно отправлено.
    """
    url = f"https://api.telegram.org/bot{settings.telegram.bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram.chat_id,
        "text": msg,
        "parse_mode": "HTML"  # Поддержка HTML-форматирования
    }
    
    for attempt in range(max_retries):
        try:
            session = await _get_session()
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status == 200:
                    result = await response.json()
                    if result.get("ok"):
                        logger.info(f"✅ Telegram message sent: {msg[:50]}...")
                        return True
                    else:
                        logger.error(
                            f"❌ Telegram API error: {result.get('description')}"
                        )
                else:
                    logger.error(f"❌ Telegram HTTP error: {response.status}")
        except asyncio.TimeoutError:
            logger.warning(
                f"⚠️ Telegram timeout (attempt {attempt + 1}/{max_retries})"
            )
        except Exception as e:
            logger.error(
                f"❌ Telegram error (attempt {attempt + 1}/{max_retries}): {e}"
            )
        
        if attempt < max_retries - 1:
            await asyncio.sleep(1)  # Пауза перед следующей попыткой
    
    return False
