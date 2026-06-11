"""Bot ishga tushirish nuqtasi: Dispatcher, routerlar, polling."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types.error_event import ErrorEvent
from django.conf import settings

from bot.config import BOT_TOKEN, BOT_USERNAME
from bot.handlers import registration, menu, testing, group
from bot.middlewares import ThrottlingMiddleware

logger = logging.getLogger(__name__)


async def _on_error(event: ErrorEvent) -> bool:
    """Global xato tutgich: bot hech qachon javobsiz qolmasin.

    Handler ichida kutilmagan xato bo'lsa — log'ga yoziladi, callback
    bo'lsa foydalanuvchiga qisqa xabar ko'rsatiladi (aks holda tugma
    cheksiz "yuklanmoqda" bo'lib qoladi).
    """
    logger.exception(
        "Update qayta ishlashda kutilmagan xato",
        exc_info=event.exception,
    )
    callback = event.update.callback_query
    if callback is not None:
        try:
            await callback.answer(
                "Texnik xato yuz berdi. Birozdan so'ng qayta urinib ko'ring.",
                show_alert=True,
            )
        except TelegramAPIError:
            pass
    return True


def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher(disable_fsm=True)
    dp.update.outer_middleware(ThrottlingMiddleware())
    dp.errors.register(_on_error)

    # Routerlar tartibi muhim: registration oxirgi message-fallback'ka ega
    dp.include_router(registration.router)
    dp.include_router(menu.router)
    dp.include_router(testing.router)
    dp.include_router(group.router)
    return dp


async def run_bot():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN sozlanmagan. .env faylida BOT_TOKEN ni to'ldiring."
        )
    if not BOT_USERNAME:
        raise RuntimeError(
            "BOT_USERNAME sozlanmagan. .env faylida BOT_USERNAME ni to'ldiring."
        )

    # DB operatsiyalari (sync_to_async, thread_sensitive=False) shu pool'da
    # bajariladi — hajmi yukka qarab .env'dagi BOT_DB_THREADS bilan sozlanadi.
    loop = asyncio.get_running_loop()
    loop.set_default_executor(
        ThreadPoolExecutor(
            max_workers=settings.BOT_DB_THREADS,
            thread_name_prefix="bot-db",
        )
    )

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = _build_dispatcher()

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(
        bot,
        tasks_concurrency_limit=settings.BOT_TASKS_CONCURRENCY,
        allowed_updates=[
            "message", "callback_query", "poll_answer", "my_chat_member",
        ],
    )
