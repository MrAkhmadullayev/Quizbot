"""
Buyruq qatoridan test import qilish (admin paneldan tashqari muqobil yo'l):

  python manage.py import_file path/to/file.pdf --test "Web 2025" --subtest "1-qism"
  python manage.py import_file path/to/file.xlsx        # Excel o'zi test/qismni biladi

Eslatma: '+' belgisi bo'lmagan savollar needs_review=True bo'lib qoladi,
ularni admin panelда to'g'rilang.
"""
from django.core.management.base import BaseCommand, CommandError

from quiz.parsers import excel_parser, text_parser
from quiz import services


class Command(BaseCommand):
    help = "Fayldan (PDF/TXT/Excel) testlarni import qiladi"

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--test", default="Nomsiz test")
        parser.add_argument("--subtest", default="1-qism")

    def handle(self, *args, **opts):
        path = opts["path"]
        lower = path.lower()
        try:
            if lower.endswith(".xlsx"):
                groups = excel_parser.parse_excel(path)
            elif lower.endswith((".pdf", ".txt")):
                questions = text_parser.parse_file(path)
                groups = [{"test": opts["test"], "subtest": opts["subtest"],
                           "questions": questions}]
            else:
                raise ValueError("Faqat .xlsx, .pdf yoki .txt fayl qabul qilinadi.")

            errors = services.validate_groups(groups)
            if errors:
                raise ValueError(" ".join(errors[:20]))
            results = services.save_grouped(groups)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Parse xatosi: {exc}")

        created = sum(r["questions_created"] for r in results)
        skipped = sum(r["questions_skipped"] for r in results)
        self.stdout.write(self.style.SUCCESS(f"✅ {created} ta savol saqlandi."))
        if skipped:
            self.stdout.write(self.style.WARNING(
                f"⚠️ {skipped} ta takroriy savol o'tkazib yuborildi."
            ))
