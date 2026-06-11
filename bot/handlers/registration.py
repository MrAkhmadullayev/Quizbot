"""Stateless ro'yxatdan o'tish: /start -> telefon raqam -> menyu."""
import re

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from bot import db, texts
from bot.keyboards import main_menu_kb, phone_request_kb

router = Router()

_PHONE_CLEAN_RE = re.compile(r"[^\d+]")


def _normalize_phone(raw):
    """Telefonni `+998...` ko'rinishiga keltiradi; yaroqsiz bo'lsa None."""
    if not raw:
        return None
    phone = _PHONE_CLEAN_RE.sub("", str(raw))
    phone = "+" + phone.lstrip("+")
    digits = phone[1:]
    if not digits.isdigit() or not 9 <= len(digits) <= 15:
        return None
    return phone


@router.message(CommandStart(), F.chat.type == "private")
async def start(message: Message):
    user = await db.get_user(message.from_user.id)
    if user and user.phone:
        await message.answer(
            texts.WELCOME_BACK,
            reply_markup=main_menu_kb(),
        )
        return
    await message.answer(
        texts.WELCOME_NEW,
        reply_markup=phone_request_kb(),
    )


@router.message(F.chat.type == "private", F.contact)
async def got_contact(message: Message):
    contact = message.contact
    # user_id'siz kontakt — telefon kitobidan forward qilingan begona raqam.
    # Faqat tugma orqali yuborilgan O'ZINING kontakti qabul qilinadi.
    if not contact.user_id or contact.user_id != message.from_user.id:
        await message.answer(
            "Iltimos, pastdagi tugma orqali o'zingizning raqamingizni yuboring.",
            reply_markup=phone_request_kb(),
        )
        return

    phone = _normalize_phone(contact.phone_number)
    if not phone:
        await message.answer(
            "Telefon raqamini o'qib bo'lmadi. Tugma orqali qayta yuboring.",
            reply_markup=phone_request_kb(),
        )
        return

    await db.create_user(
        tg_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        phone=phone,
    )
    await message.answer(
        "✅ Saqlandi.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        texts.REGISTERED,
        reply_markup=main_menu_kb(),
    )


@router.message(F.chat.type == "private")
async def private_fallback(message: Message):
    user = await db.get_user(message.from_user.id)
    if user and user.phone:
        await message.answer(
            texts.WELCOME_BACK,
            reply_markup=main_menu_kb(),
        )
        return
    await message.answer(
        "Ro'yxatdan o'tish uchun pastdagi tugma orqali "
        "telefon raqamingizni yuboring.",
        reply_markup=phone_request_kb(),
    )
