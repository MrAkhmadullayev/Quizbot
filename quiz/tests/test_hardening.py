"""Xavfsizlik va barqarorlik qatlami testlari."""
import asyncio
from types import SimpleNamespace
from unittest import mock

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage, SendPoll
from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TransactionTestCase

from bot import db
from bot.handlers.group import (
    _finish_group,
    _group_requests,
    _send_group_poll,
    _send_leaderboard,
    group_start_cmd,
)
from bot.handlers.registration import _normalize_phone
from bot.handlers.testing import _parse_id_group
from bot.middlewares import ThrottlingMiddleware
from quiz.models import (
    GroupPoll,
    KnownGroup,
    Option,
    Question,
    QuizSession,
    SubTest,
    TelegramUser,
    Test,
)


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


class GroupSessionLifecycleTests(TransactionTestCase):
    """Bitta guruhda bitta faol test + dublikat reyting himoyasi."""

    def setUp(self):
        self.user = TelegramUser.objects.create(
            tg_id=1, full_name="Owner", phone="+998901234567"
        )
        test = Test.objects.create(name="T")
        self.subtest = SubTest.objects.create(test=test, name="Q")
        question = Question.objects.create(
            subtest=self.subtest, text="S?", order=0
        )
        self.correct = Option.objects.create(
            question=question, text="A", is_correct=True, order=0
        )
        Option.objects.create(question=question, text="B", order=1)
        self.question = question
        KnownGroup.objects.create(chat_id=-10, title="G", added_by=self.user)

    def _group_session(self):
        return async_to_sync(db.create_session)(
            self.user.id, self.subtest.id, "group", chat_id=-10
        )

    def test_new_group_session_supersedes_stale_active_one(self):
        old = self._group_session()
        async_to_sync(db.save_group_poll)(
            "poll-old", 5, old.id, self.question.id,
            {"0": self.correct.id}, 0,
        )

        new = self._group_session()

        old.refresh_from_db()
        self.assertEqual(old.status, QuizSession.CANCELLED)
        self.assertTrue(
            GroupPoll.objects.get(session=old).is_closed
        )
        new.refresh_from_db()
        self.assertEqual(new.status, QuizSession.ACTIVE)

    def test_finish_group_auto_runs_only_once(self):
        session = self._group_session()

        first = async_to_sync(db.finish_group_auto)(session.id)
        second = async_to_sync(db.finish_group_auto)(session.id)

        self.assertEqual(first, {"chat_id": -10})
        self.assertIsNone(second)
        session.refresh_from_db()
        self.assertEqual(session.status, QuizSession.FINISHED)

    def test_finish_group_auto_ignores_cancelled_session(self):
        session = self._group_session()
        async_to_sync(db.cancel_session)(session.id)

        self.assertIsNone(async_to_sync(db.finish_group_auto)(session.id))
        session.refresh_from_db()
        self.assertEqual(session.status, QuizSession.CANCELLED)

    def test_finish_group_manual_runs_only_once(self):
        session = self._group_session()

        first = async_to_sync(db.finish_group_session)(
            session.id,
            self.user.tg_id,
        )
        second = async_to_sync(db.finish_group_session)(
            session.id,
            self.user.tg_id,
        )

        self.assertEqual(first, {"chat_id": -10})
        self.assertIsNone(second)

    def test_manual_finish_sends_result_even_if_poll_close_fails(self):
        session = self._group_session()
        leaderboard = mock.AsyncMock(return_value=True)

        with (
            mock.patch(
                "bot.handlers.group._close_telegram_poll",
                new=mock.AsyncMock(side_effect=RuntimeError("network")),
            ),
            mock.patch(
                "bot.handlers.group._send_leaderboard",
                new=leaderboard,
            ),
            mock.patch("bot.handlers.group.logger.exception"),
        ):
            finished = async_to_sync(_finish_group)(
                SimpleNamespace(),
                session.id,
                self.user.tg_id,
                closed_poll={
                    "chat_id": -10,
                    "message_id": 7,
                },
            )

        self.assertTrue(finished)
        leaderboard.assert_awaited_once_with(
            mock.ANY,
            session.id,
            -10,
        )

    def test_unknown_adder_does_not_clear_existing_group_owner(self):
        KnownGroup.objects.create(
            chat_id=-11,
            title="Old",
            added_by=self.user,
        )

        async_to_sync(db.register_group)(
            chat_id=-11,
            title="Updated",
            added_by_tg_id=999999,
        )

        group = KnownGroup.objects.get(chat_id=-11)
        self.assertEqual(group.title, "Updated")
        self.assertEqual(group.added_by, self.user)


class GroupLeaderboardDeliveryTests(SimpleTestCase):
    def setUp(self):
        _group_requests._locks.clear()
        _group_requests._last_call.clear()

    def test_result_retries_after_telegram_flood_control(self):
        bot = SimpleNamespace(
            send_message=mock.AsyncMock(
                side_effect=[
                    TelegramRetryAfter(
                        method=SendMessage(chat_id=-10, text="result"),
                        message="Retry later",
                        retry_after=0,
                    ),
                    None,
                ]
            )
        )

        async def run():
            with (
                mock.patch(
                    "bot.handlers.group.db.group_leaderboard",
                    new=mock.AsyncMock(return_value=[]),
                ),
                mock.patch(
                    "bot.handlers.group.asyncio.sleep",
                    new=mock.AsyncMock(),
                ),
            ):
                return await _send_leaderboard(bot, 1, -10)

        self.assertTrue(asyncio.run(run()))
        self.assertEqual(bot.send_message.await_count, 2)

    def test_poll_retries_after_telegram_flood_control(self):
        question = SimpleNamespace(id=7, text="Savol")
        options = [
            SimpleNamespace(id=11, text="A"),
            SimpleNamespace(id=12, text="B"),
        ]
        sent = SimpleNamespace(
            poll=SimpleNamespace(id="poll-id"),
            message_id=99,
        )
        bot = SimpleNamespace(
            send_poll=mock.AsyncMock(
                side_effect=[
                    TelegramRetryAfter(
                        method=SendPoll(
                            chat_id=-20,
                            question="Savol",
                            options=["A", "B"],
                        ),
                        message="Retry later",
                        retry_after=14,
                    ),
                    sent,
                ]
            ),
        )

        async def run():
            with (
                mock.patch(
                    "bot.handlers.group.db.prepare_group_question",
                    new=mock.AsyncMock(return_value={
                        "chat_id": -20,
                        "question": question,
                        "options": options,
                        "correct_index": 0,
                    }),
                ),
                mock.patch(
                    "bot.handlers.group.db.save_group_poll",
                    new=mock.AsyncMock(),
                ) as save_poll,
                mock.patch(
                    "bot.handlers.group.asyncio.sleep",
                    new=mock.AsyncMock(),
                ) as sleep,
            ):
                result = await _send_group_poll(
                    bot,
                    session_id=3,
                    index=0,
                )
                return result, save_poll, sleep

        result, save_poll, sleep = asyncio.run(run())

        self.assertEqual(result, question.id)
        self.assertEqual(bot.send_poll.await_count, 2)
        save_poll.assert_awaited_once()
        self.assertTrue(
            any(call.args[0] >= 14 for call in sleep.await_args_list)
        )

    def test_flood_error_is_raised_after_retry_limit(self):
        flood = TelegramRetryAfter(
            method=SendMessage(chat_id=-30, text="result"),
            message="Retry later",
            retry_after=1,
        )
        bot = SimpleNamespace(
            send_message=mock.AsyncMock(side_effect=flood),
        )

        async def run():
            with mock.patch(
                "bot.handlers.group.asyncio.sleep",
                new=mock.AsyncMock(),
            ):
                await _group_requests.run(
                    -30,
                    lambda: bot.send_message(-30, "result"),
                    attempts=2,
                )

        with self.assertRaises(TelegramRetryAfter):
            asyncio.run(run())
        self.assertEqual(bot.send_message.await_count, 2)


class GroupRegistrationHandlerTests(SimpleTestCase):
    def _message(self):
        return SimpleNamespace(
            chat=SimpleNamespace(
                id=-100,
                title="Production group",
            ),
            from_user=SimpleNamespace(id=77),
        )

    def test_registered_admin_can_reconnect_group_to_server_db(self):
        message = self._message()
        bot = SimpleNamespace(
            get_chat_member=mock.AsyncMock(
                return_value=SimpleNamespace(
                    status=ChatMemberStatus.ADMINISTRATOR,
                )
            ),
            send_message=mock.AsyncMock(),
        )

        async def run():
            with (
                mock.patch(
                    "bot.handlers.group.db.get_user",
                    new=mock.AsyncMock(
                        return_value=SimpleNamespace(phone="+998901234567"),
                    ),
                ),
                mock.patch(
                    "bot.handlers.group.db.register_group",
                    new=mock.AsyncMock(),
                ) as register,
                mock.patch(
                    "bot.handlers.group._group_requests.run",
                    new=mock.AsyncMock(),
                ),
            ):
                await group_start_cmd(message, bot)
                return register

        register = asyncio.run(run())
        register.assert_awaited_once_with(
            chat_id=-100,
            title="Production group",
            added_by_tg_id=77,
        )

    def test_regular_member_cannot_claim_group(self):
        message = self._message()
        bot = SimpleNamespace(
            get_chat_member=mock.AsyncMock(
                return_value=SimpleNamespace(
                    status=ChatMemberStatus.MEMBER,
                )
            ),
            send_message=mock.AsyncMock(),
        )

        async def run():
            with (
                mock.patch(
                    "bot.handlers.group.db.get_user",
                    new=mock.AsyncMock(
                        return_value=SimpleNamespace(phone="+998901234567"),
                    ),
                ),
                mock.patch(
                    "bot.handlers.group.db.register_group",
                    new=mock.AsyncMock(),
                ) as register,
                mock.patch(
                    "bot.handlers.group._group_requests.run",
                    new=mock.AsyncMock(),
                ),
            ):
                await group_start_cmd(message, bot)
                return register

        register = asyncio.run(run())
        register.assert_not_awaited()


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
