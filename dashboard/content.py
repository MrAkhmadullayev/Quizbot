"""Test / Qism / Savol / Variant uchun to'liq CRUD + ko'chirish (move).

Ierarxiya: Test → SubTest (qism) → Question (savol) → Option (variant).
Har bir darajada yangi qo'shish, tahrirlash, o'chirish va boshqa
ota-elementga ko'chirish mumkin. Model cheklovlari (2–10 variant, aynan
bitta to'g'ri javob, qism nomi test ichida noyob) qat'iy tekshiriladi.
"""
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from quiz.models import Option, Question, SubTest, Test, TestGroup

from .security import dashboard_login_required

MIN_OPTIONS = 2
MAX_OPTIONS = 10


# ============================ Yordamchilar ============================
def _next_order(model, **filters):
    agg = model.objects.filter(**filters).aggregate(m=Max("order"))
    return (agg["m"] if agg["m"] is not None else -1) + 1


def _parse_options(request):
    """Forma'dan variantlarni o'qiydi.

    Qaytaradi: (texts, correct_pos, error). texts — bo'sh bo'lmaganlar,
    correct_pos — to'g'ri javobning shu ro'yxatdagi indeksi.
    """
    raw = request.POST.getlist("opt_text")
    correct_raw = request.POST.get("correct", "")
    correct_index = int(correct_raw) if correct_raw.lstrip("-").isdigit() else -1

    texts = []
    correct_pos = None
    for i, value in enumerate(raw):
        value = value.strip()
        if not value:
            continue
        if i == correct_index:
            correct_pos = len(texts)
        texts.append(value)

    if not MIN_OPTIONS <= len(texts) <= MAX_OPTIONS:
        return None, None, (
            f"Variantlar soni {MIN_OPTIONS} tadan {MAX_OPTIONS} tagacha bo'lishi kerak."
        )
    if correct_pos is None:
        return None, None, "Aynan bitta to'g'ri javobni belgilang."
    return texts, correct_pos, None


@transaction.atomic
def _replace_options(question, texts, correct_pos):
    """Variantlarni qayta yozadi (cheklovlarni buzmaslik uchun delete+create)."""
    question.options.all().delete()
    Option.objects.bulk_create([
        Option(
            question=question,
            text=text,
            is_correct=(i == correct_pos),
            order=i,
        )
        for i, text in enumerate(texts)
    ])


# ============================ TEST ============================
@dashboard_login_required
def test_detail(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    subtests = list(
        test.subtests.annotate(qcount=Count("questions")).order_by("order", "id")
    )
    context = {
        "active": "tests",
        "test": test,
        "subtests": subtests,
        "groups": list(test.groups.all()),
    }
    return render(request, "dashboard/test_detail.html", context)


@dashboard_login_required
def test_form(request, test_id=None):
    test = get_object_or_404(Test, id=test_id) if test_id else None

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"
        group_ids = request.POST.getlist("groups")

        if not name:
            messages.error(request, "Test nomi bo'sh bo'lmasligi kerak.")
        elif Test.objects.filter(name=name).exclude(id=test_id or 0).exists():
            messages.error(request, "Bunday nomli test allaqachon mavjud.")
        else:
            if test is None:
                test = Test(name=name)
            test.name = name
            test.description = description
            test.is_active = is_active
            test.save()
            valid = list(
                TestGroup.objects.filter(id__in=group_ids).values_list("id", flat=True)
            )
            test.groups.set(valid)
            messages.success(request, f"«{name}» saqlandi.")
            return redirect("dashboard:test_detail", test_id=test.id)

    context = {
        "active": "tests",
        "test": test,
        "all_groups": list(TestGroup.objects.order_by("order", "name")),
        "selected_groups": set(test.groups.values_list("id", flat=True)) if test else set(),
    }
    return render(request, "dashboard/test_form.html", context)


@dashboard_login_required
@require_POST
def test_delete(request, test_id):
    test = get_object_or_404(Test, id=test_id)
    name = test.name
    test.delete()
    messages.success(request, f"«{name}» va uning barcha qism/savollari o'chirildi.")
    return redirect("dashboard:tests")


# ============================ QISM (SubTest) ============================
@dashboard_login_required
def subtest_detail(request, subtest_id):
    subtest = get_object_or_404(
        SubTest.objects.select_related("test"), id=subtest_id
    )
    questions = list(
        subtest.questions.prefetch_related(
            Prefetch("options", queryset=Option.objects.order_by("order", "id"))
        ).order_by("order", "id")
    )
    context = {
        "active": "tests",
        "subtest": subtest,
        "questions": questions,
    }
    return render(request, "dashboard/subtest_detail.html", context)


@dashboard_login_required
def subtest_form(request, subtest_id=None):
    subtest = (
        get_object_or_404(SubTest.objects.select_related("test"), id=subtest_id)
        if subtest_id
        else None
    )
    # Yangi qism uchun ota-test (GET ?test=)
    default_test_id = subtest.test_id if subtest else request.GET.get("test")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        order_raw = request.POST.get("order", "0").strip()
        is_active = request.POST.get("is_active") == "on"
        target_test_id = request.POST.get("test_id", "").strip()

        order = int(order_raw) if order_raw.isdigit() else 0
        target_test = Test.objects.filter(id=target_test_id).first()

        if not name:
            messages.error(request, "Qism nomi bo'sh bo'lmasligi kerak.")
        elif not target_test:
            messages.error(request, "Ota-test tanlanmadi yoki topilmadi.")
        elif (
            SubTest.objects.filter(test=target_test, name=name)
            .exclude(id=subtest_id or 0)
            .exists()
        ):
            messages.error(
                request, f"«{target_test.name}» ichида «{name}» nomli qism allaqachon mavjud."
            )
        else:
            if subtest is None:
                subtest = SubTest(test=target_test)
            subtest.name = name
            subtest.order = order
            subtest.is_active = is_active
            subtest.test = target_test  # ko'chirish (move)
            subtest.save()
            messages.success(request, f"«{name}» saqlandi.")
            return redirect("dashboard:subtest_detail", subtest_id=subtest.id)

    context = {
        "active": "tests",
        "subtest": subtest,
        "all_tests": list(Test.objects.order_by("name")),
        "default_test_id": int(default_test_id) if str(default_test_id).isdigit() else None,
    }
    return render(request, "dashboard/subtest_form.html", context)


@dashboard_login_required
@require_POST
def subtest_delete(request, subtest_id):
    subtest = get_object_or_404(SubTest, id=subtest_id)
    test_id = subtest.test_id
    name = subtest.name
    subtest.delete()
    messages.success(request, f"«{name}» qismi va savollari o'chirildi.")
    return redirect("dashboard:test_detail", test_id=test_id)


# ============================ SAVOL (Question) ============================
@dashboard_login_required
def question_form(request, question_id=None):
    question = (
        get_object_or_404(
            Question.objects.select_related("subtest", "subtest__test"),
            id=question_id,
        )
        if question_id
        else None
    )
    default_subtest_id = question.subtest_id if question else request.GET.get("subtest")

    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        target_subtest_id = request.POST.get("subtest_id", "").strip()
        target_subtest = SubTest.objects.filter(id=target_subtest_id).first()
        texts, correct_pos, opt_error = _parse_options(request)

        error = None
        if not text:
            error = "Savol matni bo'sh bo'lmasligi kerak."
        elif not target_subtest:
            error = "Qism (SubTest) tanlanmadi yoki topilmadi."
        elif opt_error:
            error = opt_error

        if error:
            messages.error(request, error)
            # Forma'ni qayta ko'rsatish uchun kiritilganlarni saqlab qolamiz
            posted_options = [
                {"text": t, "is_correct": str(i) == request.POST.get("correct", "")}
                for i, t in enumerate(request.POST.getlist("opt_text"))
            ]
            context = _question_form_context(question, default_subtest_id)
            context.update({
                "form_text": text,
                "form_subtest_id": target_subtest_id,
                "posted_options": posted_options,
            })
            return render(request, "dashboard/question_form.html", context)

        with transaction.atomic():
            moving = question is not None and question.subtest_id != target_subtest.id
            if question is None:
                question = Question(subtest=target_subtest)
                question.order = _next_order(Question, subtest=target_subtest)
            elif moving:
                question.subtest = target_subtest
                question.order = _next_order(Question, subtest=target_subtest)
            question.text = text
            question.needs_review = False
            question.save()
            _replace_options(question, texts, correct_pos)

        messages.success(request, "Savol saqlandi.")
        return redirect("dashboard:subtest_detail", subtest_id=question.subtest_id)

    context = _question_form_context(question, default_subtest_id)
    return render(request, "dashboard/question_form.html", context)


def _question_form_context(question, default_subtest_id):
    all_subtests = list(
        SubTest.objects.select_related("test").order_by("test__name", "order", "id")
    )
    existing = (
        list(question.options.order_by("order", "id")) if question else []
    )
    return {
        "active": "tests",
        "question": question,
        "all_subtests": all_subtests,
        "default_subtest_id": int(default_subtest_id)
        if str(default_subtest_id).isdigit()
        else None,
        "existing_options": existing,
        "min_options": MIN_OPTIONS,
        "max_options": MAX_OPTIONS,
    }


@dashboard_login_required
@require_POST
def question_delete(request, question_id):
    question = get_object_or_404(Question, id=question_id)
    subtest_id = question.subtest_id
    question.delete()
    messages.success(request, "Savol o'chirildi.")
    return redirect("dashboard:subtest_detail", subtest_id=subtest_id)


# ============================ GURUH VAQT SOZLAMALARI ============================
@dashboard_login_required
def group_settings(request, group_id):
    """Guruhning vaqt (taymer) sozlamalari: yoqish, 'vaqt yo'q', vaqtlar ro'yxati."""
    group = get_object_or_404(TestGroup, id=group_id)

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "save_flags":
            group.timer_enabled = request.POST.get("timer_enabled") == "on"
            group.timer_allow_none = request.POST.get("timer_allow_none") == "on"
            group.save(update_fields=["timer_enabled", "timer_allow_none"])
            messages.success(request, "Vaqt sozlamasi saqlandi.")

        elif action == "add_time":
            raw = request.POST.get("seconds", "").strip()
            if not raw.isdigit() or not (1 <= int(raw) <= 3600):
                messages.error(request, "1–3600 oralig'ida butun soniya kiriting.")
            else:
                value = int(raw)
                options = [int(x) for x in (group.timer_options or []) if str(x).isdigit()]
                if value in options:
                    messages.error(request, f"{value} soniya allaqachon mavjud.")
                else:
                    options.append(value)
                    group.timer_options = sorted(set(options))
                    group.save(update_fields=["timer_options"])
                    messages.success(request, f"{value} soniya qo'shildi.")

        elif action == "remove_time":
            raw = request.POST.get("value", "").strip()
            if raw.isdigit():
                options = [
                    int(x) for x in (group.timer_options or [])
                    if str(x).isdigit() and int(x) != int(raw)
                ]
                group.timer_options = sorted(set(options))
                group.save(update_fields=["timer_options"])
                messages.success(request, f"{raw} soniya o'chirildi.")

        return redirect("dashboard:group_settings", group_id=group.id)

    options = sorted(int(x) for x in (group.timer_options or []) if str(x).isdigit())
    context = {"active": "groups", "group": group, "options": options}
    return render(request, "dashboard/group_settings.html", context)
