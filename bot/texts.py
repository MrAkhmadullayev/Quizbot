"""Bot matnlari (bir joyda)."""
from html import escape

WELCOME_NEW = (
    "Assalomu alaykum! 👋\n\n"
    "Quiz botga xush kelibsiz. Davom etish uchun ro'yxatdan o'ting — "
    "pastdagi tugma orqali telefon raqamingizni yuboring."
)

WELCOME_BACK = "Asosiy menyu 👇"

REGISTERED = "✅ Ro'yxatdan o'tdingiz!\n\nAsosiy menyu 👇"


def _escaped_limit(value, limit):
    value = str(value)
    escaped = escape(value)
    if len(escaped) <= limit:
        return escaped

    low = 0
    high = len(value)
    while low < high:
        middle = (low + high + 1) // 2
        if len(escape(value[:middle])) <= limit - 1:
            low = middle
        else:
            high = middle - 1
    return escape(value[:low]) + "…"


def profile_text(user):
    return (
        "👤 <b>Profil</b>\n\n"
        f"<b>F.I.Sh:</b> {escape(user.full_name or '—')}\n"
        f"<b>ID:</b> <code>{user.tg_id}</code>\n"
        f"<b>Username:</b> @{escape(user.username or '—')}\n"
        f"<b>Telefon:</b> {escape(user.phone or '—')}"
    )


def question_text(index, total, q, remaining=None):
    prefix = f"<b>Savol {index + 1}/{total}</b>\n"
    if remaining is not None:
        prefix += f"⏳ Qolgan vaqt: <b>{remaining}s</b>\n"
    prefix += "\n"
    available = 4096 - len(prefix)
    return prefix + _escaped_limit(q.text, available)


def timeout_question_text(index, total, question_text_value, correct_text):
    feedback = (
        "\n\n⏱ <b>VAQT TUGADI</b>\n"
        "Siz javobni belgilamadingiz.\n"
        f"🟢 <b>To'g'ri javob:</b> {_escaped_limit(correct_text, 500)}"
    )
    prefix = f"<b>Savol {index + 1}/{total}</b>\n\n"
    available = 4096 - len(prefix) - len(feedback)
    return (
        prefix
        + _escaped_limit(question_text_value, max(1, available))
        + feedback
    )


def answered_question_text(
    index,
    total,
    question_text_value,
    selected_text,
    correct_text,
    is_correct,
):
    if is_correct:
        feedback = (
            "\n\n🟢 <b>TO'G'RI</b>\n"
            f"<b>Sizning javobingiz:</b> "
            f"{_escaped_limit(selected_text, 600)}"
        )
    else:
        feedback = (
            "\n\n🔴 <b>XATO</b>\n"
            f"<b>Sizning javobingiz:</b> "
            f"{_escaped_limit(selected_text, 500)}\n"
            f"🟢 <b>To'g'ri javob:</b> "
            f"{_escaped_limit(correct_text, 500)}"
        )

    prefix = f"<b>Savol {index + 1}/{total}</b>\n\n"
    available = 4096 - len(prefix) - len(feedback)
    return (
        prefix
        + _escaped_limit(question_text_value, max(1, available))
        + feedback
    )


def result_text(score, total):
    pct = round((score / total) * 100) if total else 0
    return (
        "🏁 <b>Test yakunlandi!</b>\n\n"
        f"To'g'ri javoblar: <b>{score}/{total}</b>\n"
        f"Natija: <b>{pct}%</b>"
    )
