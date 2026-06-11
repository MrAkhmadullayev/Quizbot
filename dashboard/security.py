"""Dashboard xavfsizligi: kirish nazorati, throttling, yordamchilar.

Dashboard mustaqil login sahifasiga ega, lekin parollarni Django'ning
xavfsiz (hash'langan) auth tizimi orqali saqlaydi. Kirish faqat
``is_staff`` bo'lgan faol foydalanuvchilarga ochiq. /admin/ alohida ishlaydi.
"""
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

LOGIN_PATH = "/dashboard/login/"

# Login throttling sozlamalari
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5 daqiqa


def get_client_ip(request):
    """Mijoz IP'sini aniqlaydi.

    X-Forwarded-For faqat ishonchli proxy (nginx) orqasida o'qiladi —
    aks holda mijoz bu headerni soxtalashtirib login-lockout'ni
    cheksiz aylanib o'tishi mumkin.
    """
    if getattr(settings, "TRUST_PROXY", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def _fail_key(ip):
    return f"dash_login_fail:{ip}"


def is_locked_out(ip):
    return cache.get(_fail_key(ip), 0) >= MAX_FAILED_ATTEMPTS


def register_failed_attempt(ip):
    key = _fail_key(ip)
    # add atomik: kalit yo'q bo'lsa TTL bilan yaratadi, bor bo'lsa incr
    if cache.add(key, 1, LOCKOUT_SECONDS):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, LOCKOUT_SECONDS)
        return 1


def reset_attempts(ip):
    cache.delete(_fail_key(ip))


def can_access(user):
    return bool(user.is_authenticated and user.is_active and user.is_staff)


def is_safe_next(url):
    """Ochiq qayta yo'naltirishning oldini olish — faqat ichki /dashboard yo'llari."""
    return (
        bool(url)
        and url.startswith("/dashboard")
        and url_has_allowed_host_and_scheme(url, allowed_hosts=None)
    )


def dashboard_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not can_access(request.user):
            if request.user.is_authenticated:
                # Tizimga kirgan, lekin ruxsati yo'q
                return redirect(f"{LOGIN_PATH}?denied=1")
            nxt = request.get_full_path()
            sep = "&" if "?" in LOGIN_PATH else "?"
            return redirect(f"{LOGIN_PATH}{sep}next={nxt}")
        return view(request, *args, **kwargs)

    return wrapper
