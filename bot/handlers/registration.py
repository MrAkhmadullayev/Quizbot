"""Stateless ro'yxatdan o'tish: /start -> telefon raqam -> menyu."""
from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove

from bot import db, texts
from bot.keyboards import main_menu_kb, phone_request_kb

router = Router()


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
    if contact.user_id and contact.user_id != message.from_user.id:
        await message.answer("Iltimos, o'zingizning raqamingizni yuboring.")
        return

    await db.create_user(
        tg_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        phone=contact.phone_number,
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
