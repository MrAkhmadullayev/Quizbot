"""Guruhda (Telegram chat) native quiz poll orqali test ishlash.

Oqim: botda guruhni va vaqtni tanlash → guruhga info + 5..1 GO sanoq →
savollar poll ko'rinishida (vaqt tanlangan bo'lsa avtomatik, taymer bilan;
aks holda boshlovchi qo'lda boshqaradi) → oxirida bitta reyting (1/2/3,
to'g'ri/xato).
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters import (
    ChatMemberUpdatedFilter,
    Command,
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
)
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    PollAnswer,
)

from bot import db
from bot.config import BOT_USERNAME
from bot.keyboards import (
    back_kb,
    group_control_kb,
    group_stop_kb,
    group_time_kb,
)

router = Router()
logger = logging.getLogger(__name__)

MAX_Q_LEN = 290
MAX_OPT_LEN = 95
POLL_GRACE = 2  # poll yopilgach keyingi savolgacha qisqa tanaffus (soniya)
GROUP_REQUEST_INTERVAL = 3.1  # Telegram: guruhda ko'pi bilan 20 xabar/minut
GROUP_REQUEST_ATTEMPTS = 5

# Avtomatik (taymerli) guruh testlari uchun fon vazifalari
_group_tasks: dict[int, asyncio.Task] = {}


class _SessionLocks:
    """Sessiya bo'yicha asyncio.Lock — ishlatilmay qolgani avtomatik o'chiriladi."""

    def __init__(self):
        self._locks: dict[int, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, session_id):
        lock, refs = self._locks.get(session_id, (None, 0))
        if lock is None:
            lock = asyncio.Lock()
        self._locks[session_id] = (lock, refs + 1)
        try:
            async with lock:
                yield
        finally:
            lock, refs = self._locks[session_id]
            if refs <= 1:
                del self._locks[session_id]
            else:
                self._locks[session_id] = (lock, refs - 1)


_session_locks = _SessionLocks()


class _ChatRequestLimiter:
    """Bitta chatga Telegram API so'rovlarini navbat bilan yuboradi."""

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._locks: dict[int, asyncio.Lock] = {}
        self._last_call: dict[int, float] = {}

    async def run(self, chat_id, operation, attempts=GROUP_REQUEST_ATTEMPTS):
        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            last_error = None
            for attempt in range(attempts):
                elapsed = time.monotonic() - self._last_call.get(
                    chat_id,
                    float("-inf"),
                )
                if elapsed < self.min_interval:
                    await asyncio.sleep(self.min_interval - elapsed)

                retry_delay = None
                try:
                    return await operation()
                except TelegramRetryAfter as exc:
                    last_error = exc
                    retry_delay = max(float(exc.retry_after), 0.0) + 0.25
                    logger.warning(
                        "Telegram flood limit: chat=%s, %.2fs kutiladi",
                        chat_id,
                        retry_delay,
                    )
                except (TelegramNetworkError, TelegramServerError) as exc:
                    last_error = exc
                    retry_delay = min(0.5 * (2 ** attempt), 4.0)
                    logger.warning(
                        "Telegram vaqtinchalik xatosi: chat=%s, %.2fs dan "
                        "keyin qayta urinish",
                        chat_id,
                        retry_delay,
                        exc_info=True,
                    )
                finally:
                    self._last_call[chat_id] = time.monotonic()

                if attempt + 1 >= attempts:
                    raise last_error
                await asyncio.sleep(retry_delay)
            raise last_error


_group_requests = _ChatRequestLimiter(GROUP_REQUEST_INTERVAL)


def _alert_text(value, limit=190):
    value = str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _parse_ints(data):
    """`prefix:a:b:c` callback'dan butun sonlar ro'yxatini xavfsiz ajratadi."""
    parts = data.split(":")[1:]
    if not parts:
        return None
    try:
        return [int(part) for part in parts]
    except ValueError:
        return None


def _message_chunks(lines, limit=3900):
    chunks, current, size = [], [], 0
    for line in lines:
        addition = len(line) + (1 if current else 0)
        if current and size + addition > limit:
            chunks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _display_name(row):
    return row["user__full_name"] or (
        "@" + row["user__username"]
        if row["user__username"]
        else str(row["user__tg_id"])
    )


# ============================ Bot guruhga qo'shilishi ============================
@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION)
)
async def bot_added_to_group(event: ChatMemberUpdated, bot: Bot):
    if event.chat.type not in ("group", "supergroup"):
        return
    await db.register_group(
        chat_id=event.chat.id,
        title=event.chat.title or "",
        added_by_tg_id=event.from_user.id if event.from_user else None,
    )
    try:
        await _group_requests.run(
            event.chat.id,
            lambda: bot.send_message(
                event.chat.id,
                "✅ <b>Bot guruhga ulandi!</b>\n\n"
                "Testni boshlash uchun botning shaxsiy chatiga o'ting, "
                "test va qismni tanlab «👥 Guruhda boshlash» bosing va shu guruhni tanlang.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🤖 Botni ochish",
                        url=f"https://t.me/{BOT_USERNAME}?start=tests",
                    )
                ]]),
            ),
        )
    except TelegramAPIError:
        pass


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION)
)
async def bot_removed_from_group(event: ChatMemberUpdated):
    if event.chat.type in ("group", "supergroup"):
        await db.deactivate_group(event.chat.id)


@router.message(Command("start"), F.chat.type.in_({"group", "supergroup"}))
async def group_start_cmd(message: Message, bot: Bot):
    """Guruhda /start uchun qisqa yo'riqnoma ko'rsatadi."""
    try:
        await _group_requests.run(
            message.chat.id,
            lambda: bot.send_message(
                message.chat.id,
                "👋 Testni boshlash uchun botning shaxsiy chatiga o'ting va "
                "shu guruhni tanlang.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🤖 Botni ochish",
                        url=f"https://t.me/{BOT_USERNAME}?start=tests",
                    )
                ]]),
            ),
        )
    except TelegramAPIError:
        pass


# ============================ Botda: guruh + vaqt tanlash ============================
@router.callback_query(F.data.startswith("group:"))
async def choose_group(cb: CallbackQuery):
    nums = _parse_ints(cb.data)
    if not nums:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    sub_id = nums[0]
    group_id = nums[1] if len(nums) > 1 else None

    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer(
            "Avval /start orqali telefon raqamingizni yuboring.",
            show_alert=True,
        )
        return

    timer = await db.get_group_timer(group_id) if group_id else None
    if timer:
        await cb.message.edit_text(
            "⏱ <b>Har bir savol uchun vaqtni tanlang:</b>",
            reply_markup=group_time_kb(
                sub_id, group_id, timer["options"], timer["allow_none"]
            ),
        )
        await cb.answer()
        return

    await _render_chats(cb, sub_id, group_id, 0)


@router.callback_query(F.data.startswith("gtime:"))
async def choose_group_time(cb: CallbackQuery):
    nums = _parse_ints(cb.data)
    if not nums or len(nums) != 3:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    sub_id, group_id, seconds = nums
    await _render_chats(cb, sub_id, group_id, seconds)


async def _render_chats(cb, sub_id, group_id, seconds):
    user = await db.get_user(cb.from_user.id)
    groups = await db.list_user_groups(user.id)

    rows = [
        [InlineKeyboardButton(
            text=f"👥 {(g.title or str(g.chat_id))[:55]}",
            callback_data=f"gstart:{sub_id}:{seconds}:{g.chat_id}",
        )]
        for g in groups
    ]
    rows.append([InlineKeyboardButton(
        text="➕ Yangi guruhga qo'shish",
        url=f"https://t.me/{BOT_USERNAME}?startgroup=sub_{sub_id}",
    )])
    back = f"backsub:{sub_id}:{group_id}" if group_id else f"backsub:{sub_id}"
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)])

    mode_note = (
        f"⏱ Vaqt: <b>{seconds}s</b> (avtomatik)" if seconds > 0
        else "🙋 Boshlovchi boshqaradi (taymersiz)"
    )
    text = (
        f"👥 <b>Qaysi guruhda boshlaymiz?</b>\n{mode_note}\n\n"
        "Yoki botni yangi guruhga qo'shing."
        if groups
        else (
            "Bot siz boshqaradigan guruhga hali qo'shilmagan.\n"
            "Botni guruhga qo'shing, so'ng bu tugmani qaytadan bosing."
        )
    )
    await cb.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("gstart:"))
async def start_group(cb: CallbackQuery, bot: Bot):
    nums = _parse_ints(cb.data)
    if not nums or len(nums) != 3:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    sub_id, seconds, chat_id = nums
    # Telegram poll open_period chegarasi [5, 600] — soxta callback'dagi
    # katta qiymat (masalan 3600) taymerni poll'dan uzoqroq uxlatib qo'yardi
    seconds = 0 if seconds <= 0 else max(5, min(seconds, 600))

    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer(
            "Avval /start orqali telefon raqamingizni yuboring.",
            show_alert=True,
        )
        return

    try:
        session = await db.create_session(
            user.id, sub_id, mode="group", chat_id=chat_id, time_limit=seconds
        )
    except db.QuizOperationError as exc:
        await cb.answer(_alert_text(exc), show_alert=True)
        return

    # Avval fon vazifasi — bot-chat xabarini tahrirlash xato bersa ham
    # guruh testi boshlanib ketadi (sessiya yetim qolmaydi)
    task = asyncio.create_task(_run_group(bot, session.id, seconds))
    _group_tasks[session.id] = task

    try:
        await cb.message.edit_text(
            "✅ Test guruhda boshlanmoqda! Guruhga o'ting 👇",
            reply_markup=back_kb(),
        )
    except TelegramAPIError:
        pass
    await cb.answer()


# ============================ Guruhda yuritish ============================
def _intro_text(info, seconds):
    mode = f"⏱ Har savolga: <b>{seconds}s</b>" if seconds > 0 else "🙋 Boshlovchi boshqaradi"
    return (
        "🎮 <b>Test boshlanmoqda!</b>\n\n"
        f"📚 Test: <b>{escape(info['test_name'])}</b>\n"
        f"🧩 Qism: <b>{escape(info['subtest_name'])}</b>\n"
        f"❓ Savollar: <b>{info['total']}</b>\n"
        f"{mode}\n"
        f"👤 Boshlovchi: {escape(info['host_name'])}"
    )


async def _countdown(bot, chat_id):
    try:
        await _group_requests.run(
            chat_id,
            lambda: bot.send_message(
                chat_id,
                "⏳ <b>Test 5 soniyadan keyin boshlanadi...</b>",
            ),
        )
    except TelegramAPIError:
        return
    await asyncio.sleep(5)


async def _run_group(bot, session_id, seconds):
    me = asyncio.current_task()
    try:
        info = await db.group_session_info(session_id)
        if not info:
            _group_tasks.pop(session_id, None)
            return
        chat_id = info["chat_id"]

        try:
            await _group_requests.run(
                chat_id,
                lambda: bot.send_message(
                    chat_id,
                    _intro_text(info, seconds),
                ),
            )
        except TelegramAPIError:
            pass
        await _countdown(bot, chat_id)

        if seconds > 0:
            await _timed_quiz(bot, session_id, info["total"], seconds, me)
        else:
            # Boshlovchi boshqaradi: birinchi pollni yuboramiz, qolganini gnext/gend
            try:
                await _send_group_poll(bot, session_id, 0, host=True)
            except db.QuizOperationError as exc:
                try:
                    await _group_requests.run(
                        chat_id,
                        lambda: bot.send_message(
                            chat_id,
                            f"⚠️ {escape(str(exc))}",
                        ),
                    )
                except TelegramAPIError:
                    pass
                await db.cancel_session(session_id)
            _group_tasks.pop(session_id, None)
    except asyncio.CancelledError:
        _group_tasks.pop(session_id, None)
        return
    except Exception:
        logger.exception("Guruh testini yuritishda kutilmagan xato")
        _group_tasks.pop(session_id, None)


async def _timed_quiz(bot, session_id, total, seconds, me):
    for index in range(total):
        if _group_tasks.get(session_id) is not me:
            return  # to'xtatildi
        try:
            question_id = await _send_group_poll(
                bot, session_id, index, open_period=seconds, host=False
            )
        except db.QuizOperationError:
            break
        await asyncio.sleep(seconds + POLL_GRACE)
        await db.close_group_poll(session_id, question_id)

    async with _session_locks.hold(session_id):
        if _group_tasks.get(session_id) is not me:
            return
        _group_tasks.pop(session_id, None)
    await _finish_group_auto(bot, session_id)


async def _send_group_poll(bot, session_id, index, open_period=None, host=True):
    data = await db.prepare_group_question(session_id, index)
    if data is None:
        raise db.QuizOperationError("Keyingi savol topilmadi.")

    question = data["question"]
    options = data["options"]
    poll_options = [option.text[:MAX_OPT_LEN] for option in options]
    if not 2 <= len(poll_options) <= 10:
        raise db.QuizOperationError(
            "Guruh polli uchun variantlar soni 2 tadan 10 tagacha bo'lishi kerak."
        )

    kwargs = {}
    if open_period:
        kwargs["open_period"] = max(5, min(int(open_period), 600))
    markup = (
        group_control_kb(session_id, question.id) if host
        else group_stop_kb(session_id)
    )

    chat_id = data["chat_id"]
    message = await _group_requests.run(
        chat_id,
        lambda: bot.send_poll(
            chat_id=chat_id,
            question=f"{index + 1}-savol: {question.text}"[:MAX_Q_LEN],
            options=poll_options,
            type="quiz",
            correct_option_id=data["correct_index"],
            is_anonymous=False,
            reply_markup=markup,
            **kwargs,
        ),
    )
    option_map = {str(i): option.id for i, option in enumerate(options)}

    try:
        await db.save_group_poll(
            message.poll.id, message.message_id, session_id,
            question.id, option_map, index,
        )
    except Exception:
        try:
            await _group_requests.run(
                chat_id,
                lambda: bot.stop_poll(
                    chat_id,
                    message.message_id,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
                ),
            )
        except TelegramAPIError:
            pass
        raise
    return question.id


@router.poll_answer()
async def on_poll_answer(poll_answer: PollAnswer):
    if not poll_answer.option_ids:
        return
    user = poll_answer.user
    await db.record_group_answer(
        poll_id=poll_answer.poll_id,
        option_index=poll_answer.option_ids[0],
        tg_id=user.id,
        username=user.username,
        full_name=user.full_name,
    )


async def _close_telegram_poll(bot, poll):
    if not poll or not poll["message_id"]:
        return
    try:
        await _group_requests.run(
            poll["chat_id"],
            lambda: bot.stop_poll(
                poll["chat_id"],
                poll["message_id"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
            ),
        )
        return
    except TelegramAPIError:
        pass
    try:
        await _group_requests.run(
            poll["chat_id"],
            lambda: bot.edit_message_reply_markup(
                chat_id=poll["chat_id"],
                message_id=poll["message_id"],
                reply_markup=None,
            ),
        )
    except TelegramAPIError:
        pass


# ============================ Boshlovchi boshqaruvi (taymersiz) ============================
@router.callback_query(F.data.startswith("gnext:"))
async def group_next(cb: CallbackQuery, bot: Bot):
    nums = _parse_ints(cb.data)
    if not nums or len(nums) != 2:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    session_id, question_id = nums
    async with _session_locks.hold(session_id):
        try:
            control = await db.get_group_control(session_id, cb.from_user.id)
            if control["status"] != "active":
                raise db.QuizOperationError("Test allaqachon yakunlangan.")

            closed = await db.close_group_poll(session_id, question_id)
            if not closed and control["current_question_id"] != question_id:
                raise db.QuizOperationError("Bu boshqaruv tugmasi allaqachon ishlatilgan.")

            next_index = control["current_index"] + 1
            if next_index >= control["total"]:
                finished = await _finish_group(
                    bot,
                    session_id,
                    cb.from_user.id,
                    closed_poll=closed,
                )
                if not finished:
                    raise db.QuizOperationError("Test allaqachon yakunlangan.")
            else:
                await _close_telegram_poll(bot, closed)
                await _send_group_poll(bot, session_id, next_index, host=True)
        except db.QuizOperationError as exc:
            await cb.answer(_alert_text(exc), show_alert=True)
            return
        except Exception:
            logger.exception("Keyingi guruh savolini yuborishda kutilmagan xato")
            await cb.answer("Keyingi savolni yuborishda texnik xato yuz berdi.", show_alert=True)
            return
        await cb.answer()


@router.callback_query(F.data.startswith("gend:"))
async def group_end(cb: CallbackQuery, bot: Bot):
    nums = _parse_ints(cb.data)
    if not nums or len(nums) != 2:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    session_id, question_id = nums
    async with _session_locks.hold(session_id):
        try:
            control = await db.get_group_control(session_id, cb.from_user.id)
            if control["status"] != "active":
                # Ikkinchi bosishda reyting qayta yuborilmasin
                raise db.QuizOperationError("Test allaqachon yakunlangan.")
            closed = await db.close_group_poll(session_id, question_id)
            finished = await _finish_group(
                bot,
                session_id,
                cb.from_user.id,
                closed_poll=closed,
            )
            if not finished:
                raise db.QuizOperationError("Test allaqachon yakunlangan.")
        except db.QuizOperationError as exc:
            await cb.answer(_alert_text(exc), show_alert=True)
            return
        except Exception:
            logger.exception("Guruh testini yakunlashda kutilmagan xato")
            await cb.answer("Testni yakunlashda texnik xato yuz berdi.", show_alert=True)
            return
        await cb.answer("Yakunlandi.")


@router.callback_query(F.data.startswith("gstop:"))
async def group_stop(cb: CallbackQuery, bot: Bot):
    """Avtomatik (taymerli) testni boshlovchi to'xtatadi."""
    nums = _parse_ints(cb.data)
    if not nums or len(nums) != 1:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    session_id = nums[0]
    try:
        await db.get_group_control(session_id, cb.from_user.id)
    except db.QuizOperationError as exc:
        await cb.answer(_alert_text(exc), show_alert=True)
        return

    task = _group_tasks.pop(session_id, None)
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()
    await _finish_group_auto(bot, session_id)
    await cb.answer("To'xtatildi.")


# ============================ Yakun + reyting ============================
async def _send_message_with_retry(bot, chat_id, text, attempts=3):
    """Natijani Telegram'ning vaqtinchalik xatolarida qayta yuboradi."""
    try:
        await _group_requests.run(
            chat_id,
            lambda: bot.send_message(chat_id, text),
            attempts=attempts,
        )
        return True
    except TelegramAPIError:
        logger.exception(
            "Guruh natijasini Telegram'ga yuborib bo'lmadi",
        )
        return False


async def _send_leaderboard(bot, session_id, chat_id):
    board = await db.group_leaderboard(session_id)
    lines = ["🏁 <b>Test yakunlandi! Natijalar:</b>", ""]
    if not board:
        lines.append("Hech kim javob bermadi.")
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(board):
            badge = medals[i] if i < 3 else f"{i + 1}."
            correct = row["correct"]
            wrong = row["total"] - correct
            lines.append(
                f"{badge} {escape(_display_name(row))} — "
                f"✅ {correct} | ❌ {wrong}"
            )
    delivered = True
    for chunk in _message_chunks(lines):
        if not await _send_message_with_retry(bot, chat_id, chunk):
            delivered = False
    return delivered


async def _finish_group(
    bot,
    session_id,
    owner_tg_id,
    closed_poll=None,
):
    result = await db.finish_group_session(session_id, owner_tg_id)
    if not result:
        return False

    # Sessiya DB'da avval yakunlanadi. Telegram pollini yopishdagi xato
    # natijani guruhga yuborishga to'sqinlik qilmasligi kerak.
    try:
        await _close_telegram_poll(bot, closed_poll)
    except Exception:
        logger.exception(
            "Poll yopilmadi, lekin guruh natijasi baribir yuboriladi",
        )
    await _send_leaderboard(bot, session_id, result["chat_id"])
    return True


async def _finish_group_auto(bot, session_id):
    result = await db.finish_group_auto(session_id)
    if not result:
        return
    await _send_leaderboard(bot, session_id, result["chat_id"])
