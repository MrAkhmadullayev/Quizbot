"""
Telegram botni ishga tushiradi:  python manage.py runbot
Django to'liq sozlangan holatda ishlaydi, shuning uchun bot ORM'dan
to'g'ridan-to'g'ri foydalanadi (sync_to_async orqali).
"""
import asyncio

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Telegram quiz botni polling rejimida ishga tushiradi"

    def handle(self, *args, **options):
        from bot.main import run_bot

        self.stdout.write(self.style.SUCCESS("🤖 Bot ishga tushmoqda..."))
        try:
            asyncio.run(run_bot())
        except (KeyboardInterrupt, SystemExit):
            self.stdout.write(self.style.WARNING("Bot to'xtatildi."))
