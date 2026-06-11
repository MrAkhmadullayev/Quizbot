"""Test/qism tanlash va yakka test ishlash logikasi."""
import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from bot import db, texts
from bot.keyboards import (
    main_menu_kb,
    options_kb,
    start_modes_kb,
    subtests_kb,
)

router = Router()
logger = logging.getLogger(__name__)


def _alert_text(value, limit=190):
    value = str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _parse_id_group(data):
    """`prefix:id` yoki `prefix:id:group_id` ni (id, group_id) ga ajratadi.

    group_id bo'lmasa None qaytaradi (eski oqim bilan moslik uchun)."""
    parts = data.split(":")
    main_id = int(parts[1])
    group_id = int(parts[2]) if len(parts) > 2 and parts[2] else None
    return main_id, group_id


@router.callback_query(F.data.startswith("test:"))
async def show_subtests(cb: CallbackQuery):
    test_id, group_id = _parse_id_group(cb.data)
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
async def start_solo(cb: CallbackQuery):
    sub_id = int(cb.data.split(":")[1])
    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer(
            "Avval /start orqali telefon raqamingizni yuboring.",
            show_alert=True,
        )
        return
    try:
        session = await db.create_session(user.id, sub_id, mode="solo")
    except db.QuizOperationError as exc:
        await cb.answer(_alert_text(exc), show_alert=True)
        return

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await _send_solo_question(
        cb,
        session.id,
        index=0,
        total=session.total,
    )
    await cb.answer()


async def _send_solo_question(cb, session_id, index, total):
    data = await db.get_session_question(session_id, index)
    if data is None:
        await cb.message.answer(
            "Savol topilmadi. Testni qaytadan boshlang.",
            reply_markup=main_menu_kb(),
        )
        return
    await cb.message.answer(
        texts.question_text(index, total, data["question"]),
        reply_markup=options_kb(session_id, data["options"]),
    )


@router.callback_query(F.data.startswith("ans:"))
async def answer_solo(cb: CallbackQuery):
    _, session_id, option_id = cb.data.split(":")
    try:
        result = await db.record_solo_answer(
            int(session_id),
            int(option_id),
            cb.from_user.id,
        )
    except db.QuizOperationError as exc:
        await cb.answer(_alert_text(exc), show_alert=True)
        return

    await cb.answer(
        "✅ To'g'ri!" if result["is_correct"] else "❌ Xato!"
    )

    feedback_text = texts.answered_question_text(
        result["question_index"],
        result["total"],
        result["question_text"],
        result["selected_text"],
        result["correct_text"],
        result["is_correct"],
    )
    try:
        await cb.message.edit_text(
            feedback_text,
            reply_markup=None,
        )
    except TelegramAPIError:
        logger.exception("Javob natijasini savol xabariga yozib bo'lmadi")
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        await cb.message.answer(feedback_text)

    if result["finished"]:
        await cb.message.answer(
            texts.result_text(result["score"], result["total"]),
            reply_markup=main_menu_kb(),
        )
        return

    await _send_solo_question(
        cb,
        int(session_id),
        result["next_index"],
        result["total"],
    )


@router.callback_query(F.data.startswith("end:"))
async def end_solo(cb: CallbackQuery):
    session_id = int(cb.data.split(":")[1])
    try:
        result = await db.finish_solo_session(
            session_id,
            cb.from_user.id,
        )
    except db.QuizOperationError as exc:
        await cb.answer(_alert_text(exc), show_alert=True)
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        pass
    await cb.message.answer(
        texts.result_text(result["score"], result["total"]),
        reply_markup=main_menu_kb(),
    )
    await cb.answer("Yakunlandi.")
