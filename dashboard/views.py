"""Dashboard ko'rinishlari (server-rendered, xavfsiz)."""
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from quiz import services
from quiz.models import Question, QuizSession, SubTest, TelegramUser, Test, TestGroup
from quiz.parsers import excel_parser, text_parser

from . import stats
from .security import (
    can_access,
    dashboard_login_required,
    get_client_ip,
    is_locked_out,
    is_safe_next,
    register_failed_attempt,
    reset_attempts,
)

UPLOAD_SESSION_KEY = "dash_upload_groups"
UPLOAD_GROUP_KEY = "dash_upload_group_id"
ALLOWED_SUFFIXES = {".xlsx", ".pdf", ".txt"}


# ----------------------------- Auth -----------------------------
def login_view(request):
    if can_access(request.user):
        return redirect("dashboard:home")

    error = None
    if request.GET.get("denied"):
        error = "Bu hisobda boshqaruv paneliga ruxsat yo'q."

    if request.method == "POST":
        ip = get_client_ip(request)
        if is_locked_out(ip):
            error = "Juda ko'p urinish. Iltimos, 5 daqiqadan so'ng qayta urinib ko'ring."
        else:
            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "")
            user = authenticate(request, username=username, password=password)
            if user is not None and user.is_active and user.is_staff:
                login(request, user)
                reset_attempts(ip)
                nxt = request.POST.get("next") or request.GET.get("next") or ""
                return redirect(nxt if is_safe_next(nxt) else "dashboard:home")
            register_failed_attempt(ip)
            error = "Login yoki parol noto'g'ri, yoki ruxsatingiz yo'q."

    context = {
        "error": error,
        "next": request.GET.get("next", ""),
    }
    return render(request, "dashboard/login.html", context)


@require_POST
def logout_view(request):
    logout(request)
    return redirect("dashboard:login")


# ----------------------------- Home -----------------------------
@dashboard_login_required
def home(request):
    context = {
        "active": "home",
        "kpi": stats.overview_kpis(),
        "recent": stats.recent_sessions(),
        "top_users": stats.top_users(),
    }
    return render(request, "dashboard/home.html", context)


# ----------------------------- Testlar -----------------------------
@dashboard_login_required
def tests(request):
    qs = (
        Test.objects.annotate(
            subtest_count=Count("subtests", distinct=True),
            question_count=Count("subtests__questions", distinct=True),
        )
        .prefetch_related("groups")
        .order_by("name")
    )
    context = {"active": "tests", "tests": list(qs)}
    return render(request, "dashboard/tests.html", context)


@dashboard_login_required
@require_POST
def test_toggle(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    test.is_active = not test.is_active
    test.save(update_fields=["is_active"])
    state = "faollashtirildi" if test.is_active else "o'chirildi"
    messages.success(request, f"«{test.name}» {state}.")
    return redirect("dashboard:tests")


# ----------------------------- Test yuklash -----------------------------
def _parse_any(path, test_name, subtest_name):
    lower = path.lower()
    if lower.endswith(".xlsx"):
        return excel_parser.parse_excel(path)
    if not lower.endswith((".pdf", ".txt")):
        raise ValueError("Qo'llab-quvvatlanmaydigan fayl turi.")
    questions = text_parser.parse_file(path)
    return [{
        "test": test_name or "Nomsiz test",
        "subtest": subtest_name or "1-qism",
        "questions": questions,
    }]


@dashboard_login_required
def upload(request):
    if request.method == "POST":
        f = request.FILES.get("file")
        test_name = request.POST.get("test_name", "").strip()
        subtest_name = request.POST.get("subtest_name", "").strip()
        group_id = request.POST.get("group_id", "").strip()

        if not f:
            messages.error(request, "Fayl tanlanmadi.")
            return redirect("dashboard:upload")
        if f.size > settings.MAX_UPLOAD_SIZE:
            messages.error(request, "Fayl hajmi ruxsat etilgan limitdan katta.")
            return redirect("dashboard:upload")

        suffix = Path(f.name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            messages.error(request, "Faqat .xlsx, .pdf yoki .txt fayl yuklash mumkin.")
            return redirect("dashboard:upload")

        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=suffix, dir=settings.MEDIA_ROOT, delete=False
        ) as out:
            tmp_path = out.name
            for chunk in f.chunks():
                out.write(chunk)

        try:
            groups = _parse_any(tmp_path, test_name, subtest_name)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Parse xatosi: {exc}")
            return redirect("dashboard:upload")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        total_q = sum(len(g["questions"]) for g in groups)
        if total_q == 0:
            messages.error(request, "Fayldan savol topilmadi. Formatni tekshiring.")
            return redirect("dashboard:upload")

        errors = services.validate_groups(groups, require_correct=False)
        if errors:
            messages.error(request, " ".join(errors[:8]))
            return redirect("dashboard:upload")

        request.session[UPLOAD_SESSION_KEY] = groups
        request.session[UPLOAD_GROUP_KEY] = group_id if group_id.isdigit() else ""
        return redirect("dashboard:upload_preview")

    context = {
        "active": "upload",
        "all_groups": list(TestGroup.objects.order_by("order", "name")),
    }
    return render(request, "dashboard/upload.html", context)


@dashboard_login_required
def upload_preview(request):
    groups = request.session.get(UPLOAD_SESSION_KEY)
    if not groups:
        messages.error(request, "Avval fayl yuklang.")
        return redirect("dashboard:upload")

    if request.method == "POST":
        missing = []
        for gi, g in enumerate(groups):
            for qi, q in enumerate(g["questions"]):
                chosen = request.POST.get(f"correct_{gi}_{qi}")
                if not chosen or not chosen.isdigit():
                    missing.append((gi, qi))
                    continue
                correct_index = int(chosen)
                if not 0 <= correct_index < len(q["options"]):
                    missing.append((gi, qi))
                    continue
                for oi, opt in enumerate(q["options"]):
                    opt["is_correct"] = oi == correct_index
                q["needs_review"] = False

        request.session[UPLOAD_SESSION_KEY] = groups
        if missing:
            messages.error(
                request,
                f"Barcha savollar uchun to'g'ri javobni tanlang. "
                f"Tanlanmagan: {len(missing)} ta.",
            )
            return redirect("dashboard:upload_preview")

        errors = services.validate_groups(groups)
        if errors:
            messages.error(request, " ".join(errors[:8]))
            return redirect("dashboard:upload_preview")

        try:
            results = services.save_grouped(groups)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("dashboard:upload_preview")

        # Ixtiyoriy: yaratilgan testlarni guruhga biriktirish
        group_id = request.session.get(UPLOAD_GROUP_KEY) or ""
        attached_to = None
        if group_id.isdigit():
            group = TestGroup.objects.filter(id=int(group_id)).first()
            if group:
                group.tests.add(*[r["test"] for r in results])
                attached_to = group.name

        request.session.pop(UPLOAD_SESSION_KEY, None)
        request.session.pop(UPLOAD_GROUP_KEY, None)

        created = sum(r["questions_created"] for r in results)
        skipped = sum(r["questions_skipped"] for r in results)
        parts = sum(len(r["subtests"]) for r in results)
        msg = f"✅ Saqlandi: {created} ta savol, {parts} ta qism. Takror: {skipped} ta."
        if attached_to:
            msg += f" «{attached_to}» guruhiga biriktirildi."
        messages.success(request, msg)
        return redirect("dashboard:tests")

    view_groups = []
    for gi, g in enumerate(groups):
        qs = []
        for qi, q in enumerate(g["questions"]):
            correct_default = next(
                (oi for oi, o in enumerate(q["options"]) if o["is_correct"]), None
            )
            qs.append({
                "gi": gi, "qi": qi, "text": q["text"],
                "options": q["options"], "correct_default": correct_default,
                "needs_review": q["needs_review"],
            })
        view_groups.append({"test": g["test"], "subtest": g["subtest"], "questions": qs})

    context = {
        "active": "upload",
        "groups": view_groups,
        "total": sum(len(g["questions"]) for g in groups),
        "needs_review": sum(
            1 for g in groups for q in g["questions"] if q["needs_review"]
        ),
    }
    return render(request, "dashboard/preview.html", context)


# ----------------------------- Guruhlar -----------------------------
@dashboard_login_required
def groups(request):
    qs = TestGroup.objects.annotate(test_count=Count("tests")).order_by("order", "name")
    context = {"active": "groups", "groups": list(qs)}
    return render(request, "dashboard/groups.html", context)


@dashboard_login_required
def group_form(request, group_id=None):
    group = get_object_or_404(TestGroup, id=group_id) if group_id else None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        order_raw = request.POST.get("order", "0").strip()
        is_active = request.POST.get("is_active") == "on"
        selected_ids = request.POST.getlist("tests")

        order = int(order_raw) if order_raw.isdigit() else 0

        if not name:
            messages.error(request, "Guruh nomi bo'sh bo'lmasligi kerak.")
        elif TestGroup.objects.filter(name=name).exclude(id=group_id or 0).exists():
            messages.error(request, "Bunday nomli guruh allaqachon mavjud.")
        else:
            if group is None:
                group = TestGroup(name=name)
            group.name = name
            group.description = description
            group.order = order
            group.is_active = is_active
            group.save()
            valid_ids = list(
                Test.objects.filter(id__in=selected_ids).values_list("id", flat=True)
            )
            group.tests.set(valid_ids)
            messages.success(request, f"«{name}» saqlandi.")
            return redirect("dashboard:groups")

    selected = set(group.tests.values_list("id", flat=True)) if group else set()
    all_tests = list(
        Test.objects.annotate(question_count=Count("subtests__questions"))
        .order_by("name")
    )
    context = {
        "active": "groups",
        "group": group,
        "all_tests": all_tests,
        "selected": selected,
    }
    return render(request, "dashboard/group_form.html", context)


@dashboard_login_required
@require_POST
def group_delete(request, group_id):
    group = get_object_or_404(TestGroup, id=group_id)
    name = group.name
    group.delete()
    messages.success(request, f"«{name}» o'chirildi.")
    return redirect("dashboard:groups")


# ----------------------------- Foydalanuvchilar -----------------------------
@dashboard_login_required
def users(request):
    search = request.GET.get("q", "").strip()
    order = request.GET.get("order", "-last_at")
    qs = stats.users_with_kpi(search=search, order=order)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    context = {
        "active": "users",
        "page": page,
        "search": search,
        "order": order,
        "total_count": paginator.count,
    }
    return render(request, "dashboard/users.html", context)


@dashboard_login_required
def user_detail(request, user_id):
    user = get_object_or_404(TelegramUser, id=user_id)
    context = {
        "active": "users",
        "tg_user": user,
        "kpi": stats.user_kpi(user),
    }
    return render(request, "dashboard/user_detail.html", context)
