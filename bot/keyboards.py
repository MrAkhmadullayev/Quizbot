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


def groups_kb(groups):
    """'Test ishlash' bosilganda chiqadigan guruhlar ro'yxati."""
    rows = [
        [
            InlineKeyboardButton(
                text=_button_text(f"📚 {g.name}"),
                callback_data=f"grp:{g.id}",
            )
        ]
        for g in groups
    ]
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _suffix(group_id):
    """Guruh konteksti bo'lsa callback'ga qo'shimcha qism qaytaradi."""
    return f":{group_id}" if group_id is not None else ""


def tests_kb(tests, group_id=None):
    rows = [
        [
            InlineKeyboardButton(
                text=_button_text(t.name),
                callback_data=f"test:{t.id}{_suffix(group_id)}",
            )
        ]
        for t in tests
    ]
    # Orqaga: guruh konteksti bo'lsa guruhlar ro'yxatiga, bo'lmasa menyuga
    back = "menu:tests" if group_id is not None else "menu:main"
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subtests_kb(test_id, subtests, group_id=None):
    rows = []
    for s in subtests:
        rows.append([InlineKeyboardButton(
            text=_button_text(f"{s.name} ({s.question_total} ta)"),
            callback_data=f"sub:{s.id}{_suffix(group_id)}",
        )])
    # Orqaga: guruh testlari ro'yxatiga (yoki eski oqimda testlar ro'yxatiga)
    back = f"grp:{group_id}" if group_id is not None else "menu:tests"
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_modes_kb(subtest_id, group_id=None):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Botda (yakka) boshlash",
                              callback_data=f"solo:{subtest_id}{_suffix(group_id)}")],
        [InlineKeyboardButton(text="👥 Guruhda boshlash",
                              callback_data=f"group:{subtest_id}{_suffix(group_id)}")],
        [InlineKeyboardButton(text="⬅️ Orqaga",
                              callback_data=f"backsub:{subtest_id}{_suffix(group_id)}")],
    ])


def solo_time_kb(subtest_id, options, allow_none, group_id=None):
    """Yakka test boshlashdan oldin vaqtni tanlash. secs=0 => taymersiz."""
    rows = []
    for seconds in options:
        rows.append([InlineKeyboardButton(
            text=f"⏱ {seconds} soniya",
            callback_data=f"tsolo:{subtest_id}:{seconds}",
        )])
    if allow_none:
        rows.append([InlineKeyboardButton(
            text="♾ Vaqtsiz",
            callback_data=f"tsolo:{subtest_id}:0",
        )])
    rows.append([InlineKeyboardButton(
        text="⬅️ Orqaga",
        callback_data=f"backsub:{subtest_id}{_suffix(group_id)}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


# Poll'da Telegram open_period chegarasi
GROUP_TIME_MIN = 5
GROUP_TIME_MAX = 600


def group_time_kb(subtest_id, group_id, options, allow_none):
    """Guruhda boshlashdan oldin vaqtni tanlash.

    secs>0 => avtomatik (poll taymeri); secs=0 => boshlovchi qo'lda boshqaradi.
    """
    rows = []
    seen = set()
    for raw in options:
        seconds = max(GROUP_TIME_MIN, min(int(raw), GROUP_TIME_MAX))
        if seconds in seen:
            continue
        seen.add(seconds)
        rows.append([InlineKeyboardButton(
            text=f"⏱ {seconds} soniya",
            callback_data=f"gtime:{subtest_id}:{group_id}:{seconds}",
        )])
    if allow_none:
        rows.append([InlineKeyboardButton(
            text="🙋 Boshlovchi boshqaradi (taymersiz)",
            callback_data=f"gtime:{subtest_id}:{group_id}:0",
        )])
    rows.append([InlineKeyboardButton(
        text="⬅️ Orqaga",
        callback_data=f"backsub:{subtest_id}{_suffix(group_id)}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def group_stop_kb(session_id):
    """Avtomatik (taymerli) guruh testida boshlovchi uchun to'xtatish."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🛑 To'xtatish",
            callback_data=f"gstop:{session_id}",
        )],
    ])
