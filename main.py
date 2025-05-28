import asyncio
from app.notifier import notify_telegram, close_session
from app.symbol_engine_manager import run_multi_symbol_bot


async def main() -> None:
    await notify_telegram("🚀 Мультимонетный бот запущен!")
    try:
        await run_multi_symbol_bot()
    except Exception as e:
        await notify_telegram(f"❌ Ошибка запуска: {e}")
        raise
    finally:
        await close_session()


if __name__ == "__main__":
    asyncio.run(main())
