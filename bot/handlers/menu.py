"""Asosiy menyu, profil va tarix."""
from html import escape

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot import db, texts
from bot.keyboards import main_menu_kb, back_kb, tests_kb

router = Router()


@router.callback_query(F.data == "menu:main")
async def back_to_main(cb: CallbackQuery):
    await cb.message.edit_text(texts.WELCOME_BACK, reply_markup=main_menu_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:profile")
async def profile(cb: CallbackQuery):
    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer("Avval /start bosing.", show_alert=True)
        return
    await cb.message.edit_text(texts.profile_text(user), reply_markup=back_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:tests")
async def tests(cb: CallbackQuery):
    tlist = await db.list_tests()
    if not tlist:
        await cb.message.edit_text(
            "Hozircha testlar yo'q. Admin test yuklashi kerak.", reply_markup=back_kb()
        )
        await cb.answer()
        return
    await cb.message.edit_text("📝 Testni tanlang:", reply_markup=tests_kb(tlist))
    await cb.answer()


@router.callback_query(F.data == "menu:history")
async def history(cb: CallbackQuery):
    user = await db.get_user(cb.from_user.id)
    if not user or not user.phone:
        await cb.answer("Avval /start bosing.", show_alert=True)
        return
    sessions = await db.user_history(user.id, limit=10)
    if not sessions:
        await cb.message.edit_text(
            "🕘 Tarix bo'sh. Hali test ishlamagansiz.", reply_markup=back_kb()
        )
        await cb.answer()
        return

    lines = ["🕘 <b>Test tarixi</b> (oxirgi 10 ta):\n"]
    status_emoji = {"finished": "✅", "active": "⏳", "cancelled": "❌"}
    for session in sessions:
        date = session["started_at"].strftime("%d.%m.%Y %H:%M")
        emo = status_emoji.get(session["status"], "•")
        mode = "👥" if session["mode"] == "group" else "🤖"
        lines.append(
            f"{emo} {mode} {escape(session['test_name'])} / "
            f"{escape(session['subtest_name'])} — "
            f"<b>{session['score']}/{session['total']}</b>  "
            f"<i>{date}</i>"
        )
    await cb.message.edit_text("\n".join(lines), reply_markup=back_kb())
    await cb.answer()
