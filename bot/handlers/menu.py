"""Asosiy menyu, profil va tarix."""
from html import escape

from aiogram import Router, F
from aiogram.types import CallbackQuery
from django.utils import timezone

from bot import db, texts
from bot.keyboards import main_menu_kb, back_kb, tests_kb, groups_kb

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
async def groups(cb: CallbackQuery):
    glist = await db.list_groups()
    if not glist:
        await cb.message.edit_text(
            "Hozircha guruhlar yo'q. Admin guruh yaratib, unga test biriktirishi kerak.",
            reply_markup=back_kb(),
        )
        await cb.answer()
        return
    await cb.message.edit_text("👥 Guruhni tanlang:", reply_markup=groups_kb(glist))
    await cb.answer()


@router.callback_query(F.data.startswith("grp:"))
async def group_tests(cb: CallbackQuery):
    try:
        group_id = int(cb.data.split(":")[1])
    except (IndexError, ValueError):
        await cb.answer("Noto'g'ri so'rov.", show_alert=True)
        return
    group = await db.get_group(group_id)
    if not group:
        await cb.answer("Guruh topilmadi yoki faol emas.", show_alert=True)
        return
    tlist = await db.list_group_tests(group_id)
    if not tlist:
        await cb.message.edit_text(
            f"📚 <b>{escape(group.name)}</b>\n\n"
            "Bu guruhda hozircha ishlashga tayyor test yo'q.",
            reply_markup=back_kb("menu:tests"),
        )
        await cb.answer()
        return
    await cb.message.edit_text(
        f"📚 <b>{escape(group.name)}</b>\n📝 Testni tanlang:",
        reply_markup=tests_kb(tlist, group_id=group_id),
    )
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
        date = timezone.localtime(session["started_at"]).strftime("%d.%m.%Y %H:%M")
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
