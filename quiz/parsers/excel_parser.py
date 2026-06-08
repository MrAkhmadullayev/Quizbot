"""
Excel (.xlsx) formatdagi testlarni parse qiladi.

Kutilgan ustunlar (1-qator — sarlavha):
    Test | SubTest | Question | Option1 | Option2 | Option3 | Option4 | Correct

  - Test:    test nomi (folder)
  - SubTest: qism nomi
  - Question: savol matni
  - Option1..4: variantlar
  - Correct: to'g'ri variant raqami (1, 2, 3 yoki 4)

Excel o'zida Test/SubTest ustunlarini olib yuradi, shuning uchun bitta
fayldan bir nechta test va qismni import qilish mumkin.
"""
import openpyxl

REQUIRED = ["test", "subtest", "question", "option1", "option2", "option3", "option4"]


def parse_excel(path: str) -> list[dict]:
    """
    Qaytaradi guruhlangan struktura:
    [{"test": str, "subtest": str,
      "questions": [{"text": str, "options":[{text,is_correct}], "needs_review": bool}]}]
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        first_row = next(rows, None)
        if first_row is None:
            return []

        header = [
            str(value).strip().lower()
            if value is not None
            else ""
            for value in first_row
        ]
        idx = {
            name: header.index(name)
            for name in REQUIRED
            if name in header
        }
        missing = [name for name in REQUIRED if name not in idx]
        if missing:
            raise ValueError(
                "Excel sarlavhasida quyidagi ustunlar yetishmayapti: "
                + ", ".join(missing)
            )
        correct_idx = (
            header.index("correct")
            if "correct" in header
            else None
        )

        grouped: dict[tuple, dict] = {}
        for row in rows:
            if not row or not any(value is not None for value in row):
                continue

            def cell(name):
                value = row[idx[name]]
                return str(value).strip() if value is not None else ""

            test = cell("test") or "Nomsiz test"
            subtest = cell("subtest") or "1-qism"
            qtext = cell("question")
            if not qtext:
                continue

            correct_num = None
            if (
                correct_idx is not None
                and correct_idx < len(row)
                and row[correct_idx] is not None
            ):
                try:
                    correct_num = int(str(row[correct_idx]).strip())
                except ValueError:
                    correct_num = None

            options = []
            for original_index in range(1, 5):
                text = cell(f"option{original_index}")
                if not text:
                    continue
                options.append({
                    "text": text,
                    "is_correct": original_index == correct_num,
                })

            correct_count = sum(
                option["is_correct"]
                for option in options
            )
            question = {
                "text": qtext,
                "options": options,
                "needs_review": correct_count != 1,
            }

            key = (test, subtest)
            grouped.setdefault(
                key,
                {
                    "test": test,
                    "subtest": subtest,
                    "questions": [],
                },
            )
            grouped[key]["questions"].append(question)

        return list(grouped.values())
    finally:
        wb.close()
