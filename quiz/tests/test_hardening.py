"""Xavfsizlik va barqarorlik qatlami testlari."""
import asyncio
from types import SimpleNamespace
from unittest import mock

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TransactionTestCase

from bot import db
from bot.handlers.registration import _normalize_phone
from bot.handlers.testing import _parse_id_group
from bot.middlewares import ThrottlingMiddleware
from quiz.models import TelegramUser


class NormalizePhoneTests(SimpleTestCase):
    def test_valid_phone_without_plus_gets_plus(self):
        self.assertEqual(_normalize_phone("998901234567"), "+998901234567")

    def test_valid_phone_with_plus_kept(self):
        self.assertEqual(_normalize_phone("+998901234567"), "+998901234567")

    def test_spaces_and_dashes_removed(self):
        self.assertEqual(_normalize_phone("+998 90 123-45-67"), "+998901234567")

    def test_garbage_rejected(self):
        self.assertIsNone(_normalize_phone("abc"))
        self.assertIsNone(_normalize_phone(""))
        self.assertIsNone(_normalize_phone(None))
        self.assertIsNone(_normalize_phone("123"))  # juda qisqa
        self.assertIsNone(_normalize_phone("1" * 20))  # juda uzun


class ParseCallbackTests(SimpleTestCase):
    def test_valid_id(self):
        self.assertEqual(_parse_id_group("sub:7"), (7, None))

    def test_valid_id_with_group(self):
        self.assertEqual(_parse_id_group("sub:7:3"), (7, 3))

    def test_crafted_data_returns_none(self):
        self.assertEqual(_parse_id_group("sub:abc"), (None, None))
        self.assertEqual(_parse_id_group("sub:"), (None, None))
        self.assertEqual(_parse_id_group("sub:1:x"), (None, None))


class CreateUserClippingTests(TransactionTestCase):
    def test_long_fields_clipped(self):
        async_to_sync(db.create_user)(
            tg_id=42,
            username="u" * 300,
            full_name="f" * 300,
            phone="+9" * 40,
        )
        user = TelegramUser.objects.get(tg_id=42)
        self.assertEqual(len(user.username), 255)
        self.assertEqual(len(user.full_name), 255)
        self.assertEqual(len(user.phone), 32)


class ThrottlingMiddlewareTests(SimpleTestCase):
    def _update(self):
        return SimpleNamespace(message=object(), callback_query=None)

    def test_excess_updates_dropped(self):
        middleware = ThrottlingMiddleware(limit=5, window=10.0)
        user = SimpleNamespace(id=1)
        handled = []

        async def handler(event, data):
            handled.append(event)

        async def run():
            for _ in range(8):
                await middleware(
                    handler, self._update(), {"event_from_user": user}
                )

        asyncio.run(run())
        self.assertEqual(len(handled), 5)

    def test_window_expiry_allows_again(self):
        middleware = ThrottlingMiddleware(limit=2, window=10.0)
        user = SimpleNamespace(id=1)
        handled = []

        async def handler(event, data):
            handled.append(event)

        async def run():
            with mock.patch("bot.middlewares.time.monotonic") as clock:
                clock.return_value = 100.0
                for _ in range(4):
                    await middleware(
                        handler, self._update(), {"event_from_user": user}
                    )
                clock.return_value = 200.0  # oyna o'tib ketdi
                await middleware(
                    handler, self._update(), {"event_from_user": user}
                )

        asyncio.run(run())
        self.assertEqual(len(handled), 3)

    def test_poll_answer_not_throttled(self):
        middleware = ThrottlingMiddleware(limit=1, window=10.0)
        user = SimpleNamespace(id=1)
        handled = []

        async def handler(event, data):
            handled.append(event)

        async def run():
            update = SimpleNamespace(message=None, callback_query=None)
            for _ in range(5):
                await middleware(handler, update, {"event_from_user": user})

        asyncio.run(run())
        self.assertEqual(len(handled), 5)

    def test_cleanup_bounds_memory(self):
        middleware = ThrottlingMiddleware(limit=5, window=10.0)
        handled = []

        async def handler(event, data):
            handled.append(event)

        async def run():
            with mock.patch("bot.middlewares.time.monotonic") as clock:
                clock.return_value = 100.0
                middleware._last_cleanup = 100.0
                for uid in range(50):
                    await middleware(
                        handler,
                        self._update(),
                        {"event_from_user": SimpleNamespace(id=uid)},
                    )
                clock.return_value = 200.0
                await middleware(
                    handler,
                    self._update(),
                    {"event_from_user": SimpleNamespace(id=999)},
                )

        asyncio.run(run())
        self.assertEqual(set(middleware._hits.keys()), {999})
