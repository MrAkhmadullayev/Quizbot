"""Dashboardga kira oladigan (is_staff) foydalanuvchi yaratish.

Misol:
    python manage.py createdashboarduser admin --password "Kuchli-Parol-123"
    python manage.py createdashboarduser admin            # parolni so'raydi
"""
import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Boshqaruv paneliga kira oladigan staff foydalanuvchi yaratadi yoki parolini yangilaydi."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Login (username)")
        parser.add_argument("--password", help="Parol (ko'rsatilmasa, so'raladi)")
        parser.add_argument("--email", default="", help="Email (ixtiyoriy)")
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Django /admin/ ham ochiq bo'lsin (superuser).",
        )

    def handle(self, *args, **options):
        username = options["username"].strip()
        password = options["password"]
        if not password:
            password = getpass.getpass("Parol: ")
            confirm = getpass.getpass("Parolni takrorlang: ")
            if password != confirm:
                raise CommandError("Parollar mos kelmadi.")
        if len(password) < 8:
            raise CommandError("Parol kamida 8 belgidan iborat bo'lishi kerak.")

        user, created = User.objects.get_or_create(username=username)
        user.email = options["email"]
        user.is_staff = True
        user.is_active = True
        if options["superuser"]:
            user.is_superuser = True
        user.set_password(password)
        user.save()

        action = "yaratildi" if created else "yangilandi"
        self.stdout.write(
            self.style.SUCCESS(f"Foydalanuvchi «{username}» {action}. Dashboardga kira oladi.")
        )
