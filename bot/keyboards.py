"""Inline va reply klaviaturalar."""
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)

def _button_text(value, limit=58):
    value = str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def phone_request_kb():
    """Ro'yxatdan o'tish — telefon raqamini so'rash."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Profil", callback_data="menu:profile")],
        [InlineKeyboardButton(text="📝 Test ishlash", callback_data="menu:tests")],
        [InlineKeyboardButton(text="🕘 Tarix", callback_data="menu:history")],
    ])


def back_kb(target="menu:main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=target)]
    ])


def tests_kb(tests):
    rows = [
        [
            InlineKeyboardButton(
                text=_button_text(t.name),
                callback_data=f"test:{t.id}",
            )
        ]
        for t in tests
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subtests_kb(test_id, subtests):
    rows = []
    for s in subtests:
        rows.append([InlineKeyboardButton(
            text=_button_text(f"{s.name} ({s.question_total} ta)"),
            callback_data=f"sub:{s.id}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:tests")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_modes_kb(subtest_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Botda (yakka) boshlash",
                              callback_data=f"solo:{subtest_id}")],
        [InlineKeyboardButton(text="👥 Guruhda boshlash",
                              callback_data=f"group:{subtest_id}")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"backsub:{subtest_id}")],
    ])


def options_kb(session_id, options):
    """Yakka test — variant tugmalari + yakunlash."""
    rows = []
    for i, opt in enumerate(options):
        rows.append([InlineKeyboardButton(
            text=_button_text(f"{chr(65 + i)}) {opt.text}"),
            callback_data=f"ans:{session_id}:{opt.id}",
        )])
    rows.append([InlineKeyboardButton(text="❌ Yakunlash",
                                      callback_data=f"end:{session_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_control_kb(session_id, question_id):
    """Guruhda — faqat boshlovchi uchun: keyingi savol / yakunlash."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➡️ Keyingi savol",
            callback_data=f"gnext:{session_id}:{question_id}",
        )],
        [InlineKeyboardButton(
            text="🏁 Yakunlash",
            callback_data=f"gend:{session_id}:{question_id}",
        )],
    ])
