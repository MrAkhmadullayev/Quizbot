"""
Admin panel.

Asosiy qism — "Test yuklash" oqimi:
  1) Admin fayl yuklaydi (Excel / PDF / TXT) + Test va Qism nomini kiritadi
  2) Tizim parse qiladi va savol/variant/to'g'ri javobni jadval ko'rinishida chiqaradi
  3) Admin har bir savol uchun to'g'ri variantni tanlaydi (PDF'da '+' bo'lmasa ham)
  4) "Saqlash" bosilganda — baza yaratiladi
"""
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.forms import BaseInlineFormSet, ValidationError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (
    TelegramUser, Test, SubTest, Question, Option,
    QuizSession, Answer, GroupPoll, KnownGroup,
)
from .parsers import excel_parser, text_parser
from . import services


# ----------------------- Oddiy modellar -----------------------
class OptionInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        options = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data
            and not form.cleaned_data.get("DELETE", False)
        ]
        if not 2 <= len(options) <= 10:
            raise ValidationError(
                "Savolda 2 tadan 10 tagacha variant bo'lishi kerak."
            )
        correct_count = sum(
            bool(option.get("is_correct"))
            for option in options
        )
        if correct_count != 1:
            raise ValidationError(
                "Aynan bitta variant to'g'ri deb belgilanishi kerak."
            )


class OptionInline(admin.TabularInline):
    model = Option
    formset = OptionInlineFormSet
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("text", "subtest", "needs_review")
    list_filter = ("subtest__test", "needs_review")
    search_fields = ("text",)
    readonly_fields = ("needs_review",)
    inlines = [OptionInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if form.instance.needs_review:
            form.instance.needs_review = False
            form.instance.save(update_fields=["needs_review"])


class SubTestInline(admin.TabularInline):
    model = SubTest
    extra = 0
    fields = ("name", "order", "is_active", "question_count")
    readonly_fields = ("question_count",)


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    list_display = ("name", "subtest_count", "is_active", "upload_link")
    inlines = [SubTestInline]
    change_list_template = "admin/quiz/test_changelist.html"

    def subtest_count(self, obj):
        return obj.subtests.count()
    subtest_count.short_description = "Qismlar"

    def upload_link(self, obj):
        return format_html('<a href="{}">Fayl yuklash</a>', reverse("admin:quiz_upload"))
    upload_link.short_description = ""

    # --- Custom URL'lar (yuklash + preview) ---
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("upload/", self.admin_site.admin_view(self.upload_view),
                 name="quiz_upload"),
            path("upload/preview/", self.admin_site.admin_view(self.preview_view),
                 name="quiz_upload_preview"),
        ]
        return custom + urls

    # 1-qadam: yuklash formasi
    def upload_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            f = request.FILES.get("file")
            test_name = request.POST.get("test_name", "").strip()
            subtest_name = request.POST.get("subtest_name", "").strip()
            if not f:
                messages.error(request, "Fayl tanlanmadi.")
                return redirect("admin:quiz_upload")
            if f.size > settings.MAX_UPLOAD_SIZE:
                messages.error(
                    request,
                    "Fayl hajmi ruxsat etilgan limitdan katta.",
                )
                return redirect("admin:quiz_upload")

            suffix = Path(f.name).suffix.lower()
            if suffix not in {".xlsx", ".pdf", ".txt"}:
                messages.error(
                    request,
                    "Faqat .xlsx, .pdf yoki .txt fayl yuklash mumkin.",
                )
                return redirect("admin:quiz_upload")

            # Vaqtincha saqlash
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=suffix,
                dir=settings.MEDIA_ROOT,
                delete=False,
            ) as out:
                tmp_path = out.name
                for chunk in f.chunks():
                    out.write(chunk)

            try:
                groups = self._parse_any(tmp_path, test_name, subtest_name)
            except Exception as exc:  # noqa: BLE001
                messages.error(request, f"Parse xatosi: {exc}")
                return redirect("admin:quiz_upload")
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            total_q = sum(len(g["questions"]) for g in groups)
            if total_q == 0:
                messages.error(request, "Fayldan savol topilmadi. Formatni tekshiring.")
                return redirect("admin:quiz_upload")
            errors = services.validate_groups(
                groups,
                require_correct=False,
            )
            if errors:
                messages.error(request, " ".join(errors[:10]))
                return redirect("admin:quiz_upload")

            # Preview uchun sessiyaga yozamiz
            request.session["upload_groups"] = groups
            return redirect("admin:quiz_upload_preview")

        context = {
            **self.admin_site.each_context(request),
            "title": "Test faylini yuklash",
        }
        return TemplateResponse(request, "admin/quiz/upload.html", context)

    def _parse_any(self, path, test_name, subtest_name):
        """Fayl turiga qarab parse qilib, [{test, subtest, questions}] qaytaradi."""
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

    # 2-qadam: ko'rib chiqish + to'g'ri javobni belgilash
    def preview_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        groups = request.session.get("upload_groups")
        if not groups:
            messages.error(request, "Avval fayl yuklang.")
            return redirect("admin:quiz_upload")

        if request.method == "POST":
            missing = []
            for gi, g in enumerate(groups):
                for qi, q in enumerate(g["questions"]):
                    field = f"correct_{gi}_{qi}"
                    chosen = request.POST.get(field)
                    if not chosen or not chosen.isdigit():
                        missing.append(f"{g['test']} / {g['subtest']} #{qi + 1}")
                        continue
                    correct_index = int(chosen)
                    if not 0 <= correct_index < len(q["options"]):
                        missing.append(f"{g['test']} / {g['subtest']} #{qi + 1}")
                        continue
                    for oi, opt in enumerate(q["options"]):
                        opt["is_correct"] = oi == correct_index
                    q["needs_review"] = False

            request.session["upload_groups"] = groups
            if missing:
                messages.error(
                    request,
                    "Barcha savollar uchun to'g'ri javobni tanlang. "
                    f"Tanlanmagan: {len(missing)} ta.",
                )
                return redirect("admin:quiz_upload_preview")

            errors = services.validate_groups(groups)
            if errors:
                messages.error(request, " ".join(errors[:10]))
                return redirect("admin:quiz_upload_preview")

            try:
                results = services.save_grouped(groups)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect("admin:quiz_upload_preview")

            del request.session["upload_groups"]
            created = sum(r["questions_created"] for r in results)
            skipped = sum(r["questions_skipped"] for r in results)
            messages.success(
                request,
                f"✅ Saqlandi: {created} ta savol, "
                f"{sum(len(r['subtests']) for r in results)} ta qism. "
                f"Takroriy o'tkazib yuborildi: {skipped} ta.",
            )
            return redirect("admin:quiz_test_changelist")

        # Preview uchun savollarni indeks bilan tayyorlaymiz
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
            **self.admin_site.each_context(request),
            "title": "Ko'rib chiqish va to'g'ri javobni belgilash",
            "groups": view_groups,
            "total": sum(len(g["questions"]) for g in groups),
            "needs_review": sum(
                1 for g in groups for q in g["questions"] if q["needs_review"]
            ),
        }
        return TemplateResponse(request, "admin/quiz/preview.html", context)


@admin.register(SubTest)
class SubTestAdmin(admin.ModelAdmin):
    list_display = ("name", "test", "order", "question_count", "is_active")
    list_filter = ("test",)


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ("full_name", "username", "tg_id", "phone", "created_at")
    search_fields = ("full_name", "username", "phone", "tg_id")


@admin.register(QuizSession)
class QuizSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "subtest", "mode", "score", "total", "status", "started_at")
    list_filter = ("mode", "status", "subtest__test")
    search_fields = ("user__full_name", "user__tg_id")
    readonly_fields = (
        "user",
        "subtest",
        "mode",
        "chat_id",
        "current_index",
        "score",
        "total",
        "question_ids",
        "status",
        "started_at",
        "finished_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "question",
        "user",
        "selected",
        "is_correct",
        "answered_at",
    )
    readonly_fields = (
        "session",
        "question",
        "user",
        "selected",
        "is_correct",
        "answered_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(GroupPoll)
class GroupPollAdmin(admin.ModelAdmin):
    list_display = (
        "poll_id",
        "session",
        "question",
        "is_closed",
        "created_at",
    )
    readonly_fields = (
        "poll_id",
        "session",
        "question",
        "message_id",
        "option_map",
        "is_closed",
        "closed_at",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(KnownGroup)

admin.site.site_header = "Quiz Bot — Boshqaruv paneli"
admin.site.site_title = "Quiz Bot Admin"
admin.site.index_title = "Boshqaruv"
