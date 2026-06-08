"""
Matn / PDF formatdagi testlarni parse qiladi.

Format (siz aytgan):
    ??? Savol matni ...        <- '?' bilan boshlangan qator = SAVOL
    = variant 1                <- '=' bilan boshlangan qator = VARIANT
    = variant 2
    + variant 3                <- '+' bilan boshlangan = TO'G'RI VARIANT
    = variant 4

Eslatma: agar faylда hech bir variant '+' bilan belgilanmagan bo'lsa
(masalan, siz yuborgan PDF — barchasi '='), savol `needs_review=True`
bo'lib qoladi va admin panelда to'g'ri javobni qo'lda belgilaydi.
"""
# Ko'p PDF eksportlarda uchraydigan "mojibake" belgilarini tuzatish
_REPLACEMENTS = {
    "ȁ8;": "ʻ",   # o' / g'  -> oʻ / gʻ
    "ȁ9;": "ʼ",   # ma'lumot -> maʼlumot
    "oȁ8;": "oʻ",
    "gȁ8;": "gʻ",
}


def normalize_uz(text: str) -> str:
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.strip()


def _is_question(line: str) -> bool:
    return line.startswith("?")


def _is_option(line: str) -> bool:
    return line.startswith("=") or line.startswith("+")


def parse_text(content: str) -> list[dict]:
    """
    Matnni savollar ro'yxatiga aylantiradi.
    Qaytaradi: [{"text": str, "options": [{"text": str, "is_correct": bool}],
                 "needs_review": bool}, ...]
    """
    lines = content.splitlines()
    questions: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur and cur["options"]:
            correct_count = sum(
                option["is_correct"]
                for option in cur["options"]
            )
            cur["needs_review"] = correct_count != 1
            questions.append(cur)
        cur = None

    for raw in lines:
        line = normalize_uz(raw)
        if not line:
            continue

        if _is_question(line):
            flush()
            qtext = line.lstrip("?").strip()
            if not qtext:
                cur = None
                continue
            cur = {
                "text": qtext,
                "options": [],
                "needs_review": False,
            }

        elif _is_option(line):
            if cur is None:
                continue  # savolsiz variant — e'tiborsiz
            is_correct = line.startswith("+")
            opt_text = line.lstrip("+=").strip()
            if not opt_text:
                continue
            cur["options"].append({"text": opt_text, "is_correct": is_correct})

        else:
            # Belgisiz qator = oldingi savol yoki variantning davomi (matn ko'chgan)
            if cur is None:
                continue
            if cur["options"]:
                cur["options"][-1]["text"] += " " + line
            else:
                cur["text"] += " " + line

    flush()
    return questions


def parse_pdf(path: str) -> list[dict]:
    """PDF'dan matn ajratib, parse_text'ga uzatadi."""
    import pdfplumber

    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return parse_text("\n".join(parts))


def parse_file(path: str) -> list[dict]:
    """Kengaytmaga qarab to'g'ri parserni tanlaydi."""
    lower = path.lower()
    if lower.endswith(".pdf"):
        return parse_pdf(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_text(f.read())
