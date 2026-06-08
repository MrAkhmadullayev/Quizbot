"""
Namuna Excel shablonini yaratadi:  python manage.py make_sample_excel
Faylni admin paneldan yuklab, formatni tushunish uchun ishlatish mumkin.
"""
import openpyxl
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Namuna test Excel shablonini yaratadi"

    def handle(self, *args, **opts):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Tests"
        ws.append(["Test", "SubTest", "Question", "Option1", "Option2",
                   "Option3", "Option4", "Correct"])
        ws.append([
            "Web Programming 2025", "1-qism",
            "PHP-da sonni satrga aylantirish uchun qaysi funksiya ishlatiladi?",
            "intval()", "strval()", "floatval()", "toString()", 2,
        ])
        ws.append([
            "Web Programming 2025", "1-qism",
            "HTML hujjati qaysi teg bilan boshlanadi?",
            "<html>", "<!DOCTYPE html>", "<head>", "<body>", 2,
        ])
        path = settings.BASE_DIR / "data" / "sample_template.xlsx"
        wb.save(path)
        self.stdout.write(self.style.SUCCESS(f"✅ Shablon yaratildi: {path}"))
