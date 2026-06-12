"""Test/qism tanlash va yakka test ishlash logikasi (taymer bilan)."""
import asyncio
import logging
import time
from collections import defaultdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from bot import db, texts
from bot.keyboards import (
    main_menu_kb,
    options_kb,
    solo_time_kb,
    start_modes_kb,
    subtests_kb,
)

router = Router()
logger = logging.getLogger(__name__)

# Yakka test taymerlari: har bir sessiya uchun fon vazifasi va qulf.
# Qulf — javob berish va vaqt tugashi bir vaqtda kelganda ikki marta
# o'tib ketmasligi uchun.
_solo_tasks: dict[int, asyncio.Task] = {}
_solo_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def _cancel_timer(session_id):
    """Sessiyaning joriy taymerini bekor qiladi (o'zini emas)."""
    task = _solo_tasks.pop(session_id, None)
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()


def _cleanup_session(session_id):
    _cancel_timer(session_id)
    _solo_locks.pop(session_id, None)


def _alert_text(value, limit=190):
    value = str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _parse_id_group(data):
    """`prefix:id` yoki `prefix:id:group_id` ni (id, group_id) ga ajratadi.

    group_id bo'lmasa None qaytaradi (eski oqim bilan moslik uchun).
    Soxta/yaroqsiz callback_data uchun (None, None) — handler'lar tekshiradi.
    """
    parts = data.split(":")
    try:
        main_id = int(parts[1])
        group_id = int(parts[2]) if len(parts) > 2 and parts[2] else None
    except (IndexError, ValueError):
        return None, None
    return main_id, group_id


@router.callback_query(F.data.startswith("test:"))
async def show_subtests(cb: CallbackQuery):
    test_id, group_id = _parse_id_group(cb.data)
    if test_id is None:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    subs = await db.list_subtests(test_id)
    if not subs:
        await cb.answer(
            "Bu testda ishlashga tayyor qismlar yo'q.",
            show_alert=True,
        )
        return
    await cb.message.edit_text(
        "📂 Qismni tanlang:",
        reply_markup=subtests_kb(test_id, subs, group_id=group_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sub:"))
async def show_start_modes(cb: CallbackQuery):
    sub_id, group_id = _parse_id_group(cb.data)
    if sub_id is None:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    sub = await db.get_subtest(sub_id)
    if not sub:
        await cb.answer("Test qismi topilmadi.", show_alert=True)
        return
    count = await db.subtest_question_count(sub_id)
    if count == 0:
        await cb.answer(
            "Bu qismdagi savollar hali tekshirilmagan.",
            show_alert=True,
        )
        return
    text = (
        f"📂 <b>{escape(sub.test.name)}</b>\n"
        f"Qism: <b>{escape(sub.name)}</b>\n"
        f"Savollar soni: <b>{count}</b>\n\n"
        "Qanday boshlaymiz?"
    )
    await cb.message.edit_text(
        text, reply_markup=start_modes_kb(sub_id, group_id=group_id)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("backsub:"))
async def back_to_subtests(cb: CallbackQuery):
    sub_id, group_id = _parse_id_group(cb.data)
    if sub_id is None:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    sub = await db.get_subtest(sub_id)
    if not sub:
        await cb.answer("Test qismi topilmadi.", show_alert=True)
        return
    subs = await db.list_subtests(sub.test_id)
    await cb.message.edit_text(
        "📂 Qismni tanlang:",
        reply_markup=subtests_kb(sub.test_id, subs, group_id=group_id),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("solo:"))
async def choose_solo(cb: CallbackQuery, bot: Bot):
    """Yakka rejim: guruhda vaqt sozlamasi yoqilgan bo'lsa — vaqt tanlash."""
    sub_id, group_id = _parse_id_group(cb.data)
    if sub_id is None:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
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
            "⏱ <b>Vaqtni tanlang</b>\nHar bir savol uchun beriladigan vaqt:",
            reply_markup=solo_time_kb(
                sub_id, timer["options"], timer["allow_none"], group_id=group_id
            ),
        )
        await cb.answer()
        return

    await _begin_solo(cb, bot, sub_id, 0)


@router.callback_query(F.data.startswith("tsolo:"))
async def start_solo_timed(cb: CallbackQuery, bot: Bot):
    parts = cb.data.split(":")
    try:
        sub_id, seconds = int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    await _begin_solo(cb, bot, sub_id, max(0, min(seconds, 3600)))


async def _begin_solo(cb: CallbackQuery, bot: Bot, sub_id, time_limit):
    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer(
            "Avval /start orqali telefon raqamingizni yuboring.",
            show_alert=True,
        )
        return
    try:
        session = await db.create_session(
            user.id, sub_id, mode="solo", time_limit=time_limit
        )
    except db.QuizOperationError as exc:
        await cb.answer(_alert_text(exc), show_alert=True)
        return

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await cb.answer()
    await _send_solo_question(
        bot,
        cb.message.chat.id,
        session.id,
        cb.from_user.id,
        index=0,
        total=session.total,
        time_limit=session.time_limit,
    )


async def _send_solo_question(bot, chat_id, session_id, tg_id, index, total, time_limit):
    data = await db.get_session_question(session_id, index)
    if data is None:
        _cleanup_session(session_id)
        await bot.send_message(
            chat_id,
            "Savol topilmadi. Testni qaytadan boshlang.",
            reply_markup=main_menu_kb(),
        )
        return

    question = data["question"]
    options = data["options"]
    remaining = time_limit if time_limit > 0 else None
    msg = await bot.send_message(
        chat_id,
        texts.question_text(index, total, question, remaining=remaining),
        reply_markup=options_kb(session_id, options),
    )

    if time_limit > 0:
        task = asyncio.create_task(
            _run_timer(
                bot, chat_id, session_id, tg_id, index, total,
                time_limit, msg.message_id, question, options,
            )
        )
        _solo_tasks[session_id] = task


async def _run_timer(
    bot, chat_id, session_id, tg_id, index, total,
    seconds, message_id, question, options,
):
    """Savol uchun teskari sanoq; vaqt tugasa to'g'ri javobni ochib o'tadi."""
    me = asyncio.current_task()
    try:
        deadline = time.monotonic() + seconds
        while True:
            remaining = int(round(deadline - time.monotonic()))
            if remaining <= 0:
                break
            if _solo_tasks.get(session_id) is not me:
                return  # boshqa savolga o'tilgan — bu taymer eskirgan
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=texts.question_text(index, total, question, remaining=remaining),
                    reply_markup=options_kb(session_id, options),
                )
            except TelegramAPIError:
                pass  # flood/edit xatosi — sanoq baribir to'g'ri tugaydi
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return

    # Vaqt tugadi — javobsiz keyingisiga o'tamiz (qulf bilan, javob bilan to'qnashmaslik uchun)
    async with _solo_locks[session_id]:
        if _solo_tasks.get(session_id) is not me:
            return
        result = await db.skip_solo_question(session_id, tg_id, index)
        if result is None:
            return
        _solo_tasks.pop(session_id, None)

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=texts.timeout_question_text(
                index, total, result["question_text"], result["correct_text"]
            ),
            reply_markup=None,
        )
    except TelegramAPIError:
        pass

    if result["finished"]:
        _cleanup_session(session_id)
        await bot.send_message(
            chat_id,
            texts.result_text(result["score"], result["total"]),
            reply_markup=main_menu_kb(),
        )
    else:
        await _send_solo_question(
            bot, chat_id, session_id, tg_id,
            result["next_index"], total, result["time_limit"],
        )


@router.callback_query(F.data.startswith("ans:"))
async def answer_solo(cb: CallbackQuery, bot: Bot):
    parts = cb.data.split(":")
    try:
        session_id, option_id = int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return

    async with _solo_locks[session_id]:
        try:
            result = await db.record_solo_answer(
                session_id, option_id, cb.from_user.id
            )
        except db.QuizOperationError as exc:
            await cb.answer(_alert_text(exc), show_alert=True)
            return
        _cancel_timer(session_id)

    await cb.answer("✅ To'g'ri!" if result["is_correct"] else "❌ Xato!")

    feedback_text = texts.answered_question_text(
        result["question_index"],
        result["total"],
        result["question_text"],
        result["selected_text"],
        result["correct_text"],
        result["is_correct"],
    )
    try:
        await cb.message.edit_text(feedback_text, reply_markup=None)
    except TelegramAPIError:
        logger.exception("Javob natijasini savol xabariga yozib bo'lmadi")
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await cb.message.answer(feedback_text)

    if result["finished"]:
        _cleanup_session(session_id)
        await cb.message.answer(
            texts.result_text(result["score"], result["total"]),
            reply_markup=main_menu_kb(),
        )
        return

    await _send_solo_question(
        bot,
        cb.message.chat.id,
        session_id,
        cb.from_user.id,
        result["next_index"],
        result["total"],
        result["time_limit"],
    )


@router.callback_query(F.data.startswith("end:"))
async def end_solo(cb: CallbackQuery):
    session_id, _ = _parse_id_group(cb.data)
    if session_id is None:
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    async with _solo_locks[session_id]:
        try:
            result = await db.finish_solo_session(session_id, cb.from_user.id)
        except db.QuizOperationError as exc:
            await cb.answer(_alert_text(exc), show_alert=True)
            return
        _cancel_timer(session_id)
    _cleanup_session(session_id)

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await cb.message.answer(
        texts.result_text(result["score"], result["total"]),
        reply_markup=main_menu_kb(),
    )
    await cb.answer("Yakunlandi.")
