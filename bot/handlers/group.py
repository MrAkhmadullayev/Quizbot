"""Guruhda native Telegram quiz poll orqali test ishlash logikasi."""
import asyncio
import logging
from collections import defaultdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import (
    ChatMemberUpdatedFilter,
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
)
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    PollAnswer,
)

from bot import db
from bot.keyboards import back_kb, group_control_kb

router = Router()
logger = logging.getLogger(__name__)

MAX_Q_LEN = 290
MAX_OPT_LEN = 95
_session_locks = defaultdict(asyncio.Lock)


def _alert_text(value, limit=190):
    value = str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _message_chunks(lines, limit=3900):
    chunks = []
    current = []
    size = 0
    for line in lines:
        addition = len(line) + (1 if current else 0)
        if current and size + addition > limit:
            chunks.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += len(line) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append("\n".join(current))
    return chunks


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION)
)
async def bot_added_to_group(event: ChatMemberUpdated):
    if event.chat.type in ("group", "supergroup"):
        await db.register_group(
            chat_id=event.chat.id,
            title=event.chat.title or "",
            added_by_tg_id=event.from_user.id if event.from_user else None,
        )


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION)
)
async def bot_removed_from_group(event: ChatMemberUpdated):
    if event.chat.type in ("group", "supergroup"):
        await db.deactivate_group(event.chat.id)


@router.callback_query(F.data.startswith("group:"))
async def choose_group(cb: CallbackQuery):
    sub_id = int(cb.data.split(":")[1])
    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer(
            "Avval /start orqali telefon raqamingizni yuboring.",
            show_alert=True,
        )
        return

    groups = await db.list_user_groups(user.id)
    rows = [
        [
            InlineKeyboardButton(
                text=f"👥 {(group.title or str(group.chat_id))[:55]}",
                callback_data=f"gstart:{sub_id}:{group.chat_id}",
            )
        ]
        for group in groups
    ]

    from bot.config import BOT_USERNAME

    rows.append([
        InlineKeyboardButton(
            text="➕ Yangi guruhga qo'shish",
            url=f"https://t.me/{BOT_USERNAME}?startgroup=sub_{sub_id}",
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text="⬅️ Orqaga",
            callback_data=f"backsub:{sub_id}",
        )
    ])

    text = (
        "👥 Qaysi guruhda boshlaymiz?\n"
        "Yoki botni yangi guruhga qo'shing."
        if groups
        else (
            "Bot siz boshqaradigan guruhga hali qo'shilmagan.\n"
            "Botni guruhga qo'shing, so'ng bu tugmani qaytadan bosing."
        )
    )
    await cb.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("gstart:"))
async def start_group(cb: CallbackQuery, bot: Bot):
    _, sub_id, chat_id = cb.data.split(":")
    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer(
            "Avval /start orqali telefon raqamingizni yuboring.",
            show_alert=True,
        )
        return

    session = None
    try:
        session = await db.create_session(
            user.id,
            int(sub_id),
            mode="group",
            chat_id=int(chat_id),
        )
        subtest = await db.get_subtest(int(sub_id))
        await bot.send_message(
            int(chat_id),
            (
                f"🎮 <b>{escape(subtest.test.name)} / "
                f"{escape(subtest.name)}</b> boshlandi!\n"
                f"Boshlovchi: {escape(user.full_name)}\n"
                f"Savollar soni: {session.total}\n\n"
                "Har bir savolga javob bering. Faqat boshlovchi "
                "keyingi savolga o'tkaza oladi."
            ),
        )
        await _send_group_poll(bot, session.id, 0)
    except db.QuizOperationError as exc:
        if session:
            await db.cancel_session(session.id)
            _session_locks.pop(session.id, None)
        await cb.answer(
            _alert_text(exc),
            show_alert=True,
        )
        return
    except Exception:
        logger.exception("Guruh testini boshlashda kutilmagan xato")
        if session:
            await db.cancel_session(session.id)
            _session_locks.pop(session.id, None)
        await cb.answer(
            "Guruh testini boshlashda texnik xato yuz berdi.",
            show_alert=True,
        )
        return

    await cb.message.edit_text(
        "✅ Test guruhda boshlandi!",
        reply_markup=back_kb(),
    )
    await cb.answer()


async def _send_group_poll(bot, session_id, index):
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

    message = await bot.send_poll(
        chat_id=data["chat_id"],
        question=f"{index + 1}-savol: {question.text}"[:MAX_Q_LEN],
        options=poll_options,
        type="quiz",
        correct_option_id=data["correct_index"],
        is_anonymous=False,
        reply_markup=group_control_kb(session_id, question.id),
    )
    option_map = {
        str(i): option.id
        for i, option in enumerate(options)
    }

    try:
        await db.save_group_poll(
            message.poll.id,
            message.message_id,
            session_id,
            question.id,
            option_map,
            index,
        )
    except Exception:
        try:
            await bot.stop_poll(data["chat_id"], message.message_id)
        except TelegramAPIError:
            pass
        raise

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
        await bot.stop_poll(poll["chat_id"], poll["message_id"])
    except TelegramAPIError:
        pass
    try:
        await bot.edit_message_reply_markup(
            chat_id=poll["chat_id"],
            message_id=poll["message_id"],
            reply_markup=None,
        )
    except TelegramAPIError:
        pass


@router.callback_query(F.data.startswith("gnext:"))
async def group_next(cb: CallbackQuery, bot: Bot):
    _, session_id, question_id = cb.data.split(":")
    session_id = int(session_id)
    async with _session_locks[session_id]:
        try:
            control = await db.get_group_control(
                session_id,
                cb.from_user.id,
            )
            if control["status"] != "active":
                raise db.QuizOperationError("Test allaqachon yakunlangan.")

            closed = await db.close_group_poll(
                session_id,
                int(question_id),
            )
            if (
                not closed
                and control["current_question_id"] != int(question_id)
            ):
                raise db.QuizOperationError(
                    "Bu boshqaruv tugmasi allaqachon ishlatilgan."
                )
            await _close_telegram_poll(bot, closed)

            next_index = control["current_index"] + 1
            if next_index >= control["total"]:
                await _finish_group(
                    bot,
                    session_id,
                    cb.from_user.id,
                )
            else:
                await _send_group_poll(bot, session_id, next_index)
        except db.QuizOperationError as exc:
            await cb.answer(_alert_text(exc), show_alert=True)
            return
        except Exception:
            logger.exception(
                "Keyingi guruh savolini yuborishda kutilmagan xato",
            )
            await cb.answer(
                "Keyingi savolni yuborishda texnik xato yuz berdi.",
                show_alert=True,
            )
            return

        await cb.answer()


@router.callback_query(F.data.startswith("gend:"))
async def group_end(cb: CallbackQuery, bot: Bot):
    _, session_id, question_id = cb.data.split(":")
    session_id = int(session_id)
    async with _session_locks[session_id]:
        try:
            await db.get_group_control(session_id, cb.from_user.id)
            closed = await db.close_group_poll(
                session_id,
                int(question_id),
            )
            await _close_telegram_poll(bot, closed)
            await _finish_group(bot, session_id, cb.from_user.id)
        except db.QuizOperationError as exc:
            await cb.answer(_alert_text(exc), show_alert=True)
            return
        except Exception:
            logger.exception("Guruh testini yakunlashda kutilmagan xato")
            await cb.answer(
                "Testni yakunlashda texnik xato yuz berdi.",
                show_alert=True,
            )
            return

        await cb.answer("Yakunlandi.")


async def _finish_group(bot, session_id, owner_tg_id):
    result = await db.finish_group_session(session_id, owner_tg_id)
    board = await db.group_leaderboard(session_id)
    lines = ["🏁 <b>Test yakunlandi! Natijalar:</b>", ""]
    if not board:
        lines.append("Hech kim javob bermadi.")
    else:
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(board):
            raw_name = row["user__full_name"] or (
                "@" + row["user__username"]
                if row["user__username"]
                else str(row["user__tg_id"])
            )
            badge = medals[i] if i < 3 else f"{i + 1}."
            lines.append(
                f"{badge} {escape(raw_name)} — "
                f"{row['correct']}/{row['total']}"
            )

    for chunk in _message_chunks(lines):
        await bot.send_message(result["chat_id"], chunk)
    _session_locks.pop(session_id, None)
