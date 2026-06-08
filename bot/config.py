"""Bot sozlamalari — Django settingsdan o'qiladi."""
from django.conf import settings

BOT_TOKEN = settings.BOT_TOKEN
BOT_USERNAME = settings.BOT_USERNAME.lstrip("@")
