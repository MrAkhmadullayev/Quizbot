"""Bot ishga tushirish nuqtasi: Dispatcher, routerlar, polling."""
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import BOT_TOKEN, BOT_USERNAME
from bot.handlers import registration, menu, testing, group

logging.basicConfig(level=logging.INFO)


async def run_bot():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN sozlanmagan. .env faylida BOT_TOKEN ni to'ldiring."
        )
    if not BOT_USERNAME:
        raise RuntimeError(
            "BOT_USERNAME sozlanmagan. .env faylida BOT_USERNAME ni to'ldiring."
        )

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(disable_fsm=True)

    # Routerlar tartibi muhim
    dp.include_router(registration.router)
    dp.include_router(menu.router)
    dp.include_router(testing.router)
    dp.include_router(group.router)

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(
        bot,
        tasks_concurrency_limit=100,
        allowed_updates=[
            "message", "callback_query", "poll_answer", "my_chat_member",
        ],
    )
