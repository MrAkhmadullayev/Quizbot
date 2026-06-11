"""Bot middleware'lari: yengil anti-flood (tashqi xizmatsiz, xotirada)."""
import logging
import time
from collections import deque

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Update

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Har bir foydalanuvchi uchun sliding-window rate limit.

    `window` soniya ichida `limit` tadan ortiq xabar/callback yuborgan
    foydalanuvchining ortiqcha update'lari jimgina tashlab yuboriladi
    (birinchi oshganda bitta ogohlantirish ko'rsatiladi). Bu DB va
    Telegram API'ni bitta foydalanuvchi spamidan himoya qiladi.

    poll_answer va my_chat_member cheklanmaydi — guruhda yuzlab odam
    bir vaqtda javob berishi normal holat.

    Xotira chegaralangan: faqat oxirgi `window` ichida faol bo'lgan
    foydalanuvchilar saqlanadi, qolganlari muntazam tozalanadi.
    """

    def __init__(self, limit=25, window=10.0):
        self.limit = limit
        self.window = window
        self._hits: dict[int, deque] = {}
        self._last_cleanup = time.monotonic()

    async def __call__(self, handler, event: Update, data):
        if event.message is None and event.callback_query is None:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        self._cleanup(now)

        hits = self._hits.setdefault(user.id, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()

        if len(hits) >= self.limit:
            # Limitga yetganda faqat bir marta ogohlantiramiz
            if len(hits) == self.limit and event.callback_query is not None:
                hits.append(now)
                try:
                    await event.callback_query.answer(
                        "Juda tez bosyapsiz. Biroz kuting.",
                        show_alert=False,
                    )
                except TelegramAPIError:
                    pass
            return None

        hits.append(now)
        return await handler(event, data)

    def _cleanup(self, now):
        if now - self._last_cleanup < self.window:
            return
        self._last_cleanup = now
        stale = [
            user_id
            for user_id, hits in self._hits.items()
            if not hits or now - hits[-1] > self.window
        ]
        for user_id in stale:
            del self._hits[user_id]
