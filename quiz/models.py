"""
Ma'lumotlar bazasi modellari.

Ierarxiya (siz aytgan struktura):
    Test (folder / test nomi)
      └── SubTest (qism — 700 savol qismlarga bo'linadi)
            └── Question (savol)
                  └── Option (4 ta variant, biri to'g'ri)

Sessiyalar:
    QuizSession — bitta test ishlash jarayoni (yakka yoki guruh)
      └── Answer  — har bir berilgan javob
    GroupPoll    — guruhdagi native quiz poll bilan savolni bog'lash uchun
"""
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class TelegramUser(models.Model):
    tg_id = models.BigIntegerField("Telegram ID", unique=True, db_index=True)
    username = models.CharField("Username", max_length=255, blank=True, null=True)
    full_name = models.CharField("F.I.Sh", max_length=255, blank=True)
    phone = models.CharField("Telefon", max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"

    def __str__(self):
        return self.full_name or self.username or str(self.tg_id)


class Test(models.Model):
    name = models.CharField("Test nomi", max_length=255, unique=True)
    description = models.TextField("Tavsif", blank=True)
    is_active = models.BooleanField("Faol", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Test"
        verbose_name_plural = "Testlar"
        ordering = ["name"]

    def __str__(self):
        return self.name


class TestGroup(models.Model):
    """Testlarni guruhlash uchun (fan / sinf / yo'nalish).

    Foydalanuvchi "Test ishlash" -> avval guruhni tanlaydi -> shu guruhga
    biriktirilgan testlar ro'yxati chiqadi. Bir test bir nechta guruhda
    ko'rinishi mumkin (ManyToMany).

    Diqqat: bu Telegram chat guruhi (KnownGroup) emas — bu test kategoriyasi.
    """
    name = models.CharField("Guruh nomi", max_length=255, unique=True)
    description = models.TextField("Tavsif", blank=True)
    order = models.PositiveIntegerField("Tartib", default=0)
    is_active = models.BooleanField("Faol", default=True)
    tests = models.ManyToManyField(
        "Test",
        related_name="groups",
        blank=True,
        verbose_name="Testlar",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Guruh"
        verbose_name_plural = "Guruhlar"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class SubTest(models.Model):
    """Test ichidagi qism (masalan: 1-qism, 2-qism ...)."""
    test = models.ForeignKey(Test, related_name="subtests", on_delete=models.CASCADE)
    name = models.CharField("Qism nomi", max_length=255)
    order = models.PositiveIntegerField("Tartib", default=0)
    is_active = models.BooleanField("Faol", default=True)

    class Meta:
        verbose_name = "Test qismi"
        verbose_name_plural = "Test qismlari"
        ordering = ["order", "id"]
        unique_together = ("test", "name")

    def __str__(self):
        return f"{self.test.name} / {self.name}"

    @property
    def question_count(self):
        return self.questions.count()


class Question(models.Model):
    subtest = models.ForeignKey(SubTest, related_name="questions", on_delete=models.CASCADE)
    text = models.TextField("Savol matni")
    order = models.PositiveIntegerField("Tartib", default=0)
    # PDF importida `+` belgisi bo'lmasa, to'g'ri javob noaniq -> admin tekshirsin
    needs_review = models.BooleanField("Tekshirish kerak", default=False)

    class Meta:
        verbose_name = "Savol"
        verbose_name_plural = "Savollar"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["subtest", "order"],
                name="unique_question_order_per_subtest",
            ),
        ]

    def __str__(self):
        return self.text[:70]


class Option(models.Model):
    question = models.ForeignKey(Question, related_name="options", on_delete=models.CASCADE)
    text = models.TextField("Variant")
    is_correct = models.BooleanField("To'g'ri javob", default=False)
    order = models.PositiveIntegerField("Tartib", default=0)

    class Meta:
        verbose_name = "Variant"
        verbose_name_plural = "Variantlar"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "order"],
                name="unique_option_order_per_question",
            ),
            models.UniqueConstraint(
                fields=["question"],
                condition=models.Q(is_correct=True),
                name="unique_correct_option_per_question",
            ),
        ]

    def __str__(self):
        return ("✅ " if self.is_correct else "▫️ ") + self.text[:50]


class QuizSession(models.Model):
    SOLO = "solo"
    GROUP = "group"
    MODE_CHOICES = [(SOLO, "Yakka (botda)"), (GROUP, "Guruhda")]

    ACTIVE = "active"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (ACTIVE, "Davom etmoqda"),
        (FINISHED, "Yakunlangan"),
        (CANCELLED, "Bekor qilingan"),
    ]

    user = models.ForeignKey(TelegramUser, related_name="sessions", on_delete=models.CASCADE)
    subtest = models.ForeignKey(SubTest, on_delete=models.CASCADE)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=SOLO)
    chat_id = models.BigIntegerField("Guruh chat_id", null=True, blank=True)
    current_index = models.PositiveIntegerField(default=0)  # navbatdagi savol indeksi
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    question_ids = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Sessiya"
        verbose_name_plural = "Sessiyalar (tarix)"
        ordering = ["-started_at"]
        indexes = [
            # Tarix sahifasi uchun issiq yo'l: user + mode bo'yicha so'nggilar
            models.Index(
                fields=["user", "mode", "-started_at"],
                name="session_user_mode_started",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(current_index__lte=models.F("total")),
                name="session_index_not_above_total",
            ),
            models.CheckConstraint(
                condition=models.Q(score__lte=models.F("total")),
                name="session_score_not_above_total",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(mode="group", chat_id__isnull=False)
                    | models.Q(mode="solo", chat_id__isnull=True)
                ),
                name="session_mode_chat_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.subtest} ({self.get_mode_display()})"

    def finish(self):
        self.status = self.FINISHED
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at"])


class Answer(models.Model):
    session = models.ForeignKey(QuizSession, related_name="answers", on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    # Guruh rejimida javob beruvchi sessiya egasidan farq qilishi mumkin
    user = models.ForeignKey(TelegramUser, null=True, blank=True, on_delete=models.SET_NULL)
    selected = models.ForeignKey(Option, null=True, blank=True, on_delete=models.SET_NULL)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Javob"
        verbose_name_plural = "Javoblar"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "question", "user"],
                condition=models.Q(user__isnull=False),
                name="unique_user_answer_per_session_question",
            ),
        ]

    def clean(self):
        errors = {}
        if (
            self.selected_id
            and self.question_id
            and self.selected.question_id != self.question_id
        ):
            errors["selected"] = "Variant tanlangan savolga tegishli emas."
        if (
            self.session_id
            and self.question_id
            and self.session.subtest_id != self.question.subtest_id
        ):
            errors["question"] = "Savol sessiya qismiga tegishli emas."
        if errors:
            raise ValidationError(errors)


class GroupPoll(models.Model):
    """Telegram native quiz poll'ni savol/sessiya bilan bog'laydi (poll_answer kelganda)."""
    poll_id = models.CharField(max_length=255, unique=True, db_index=True)
    session = models.ForeignKey(QuizSession, related_name="polls", on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    message_id = models.PositiveBigIntegerField(null=True, blank=True)
    # poll variant indeksi -> Option id (poll_answer faqat indeks beradi)
    option_map = models.JSONField(default=dict)
    is_closed = models.BooleanField(default=False, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "question"],
                name="unique_poll_per_session_question",
            ),
        ]

    def clean(self):
        if (
            self.session_id
            and self.question_id
            and self.session.subtest_id != self.question.subtest_id
        ):
            raise ValidationError(
                {"question": "Poll savoli sessiya qismiga tegishli emas."}
            )


class KnownGroup(models.Model):
    """Bot qo'shilgan guruhlar (my_chat_member orqali avtomatik yoziladi)."""
    chat_id = models.BigIntegerField(unique=True)
    title = models.CharField(max_length=255, blank=True)
    added_by = models.ForeignKey(
        TelegramUser, null=True, blank=True, on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title or str(self.chat_id)
