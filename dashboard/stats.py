"""KPI hisob-kitoblari (tez, agregat so'rovlar bilan)."""
from django.db.models import Avg, Count, F, FloatField, Max, Q
from django.db.models.functions import Cast

from quiz.models import (
    Answer,
    Question,
    QuizSession,
    SubTest,
    TelegramUser,
    Test,
    TestGroup,
)

SOLO = QuizSession.SOLO
GROUP = QuizSession.GROUP
FINISHED = QuizSession.FINISHED
ACTIVE = QuizSession.ACTIVE
CANCELLED = QuizSession.CANCELLED


def overview_kpis():
    sessions = QuizSession.objects.all()
    agg = sessions.aggregate(
        total=Count("id"),
        finished=Count("id", filter=Q(status=FINISHED)),
        active=Count("id", filter=Q(status=ACTIVE)),
        cancelled=Count("id", filter=Q(status=CANCELLED)),
        solo=Count("id", filter=Q(mode=SOLO)),
        group=Count("id", filter=Q(mode=GROUP)),
    )
    return {
        "users": TelegramUser.objects.count(),
        "tests": Test.objects.count(),
        "subtests": SubTest.objects.count(),
        "questions": Question.objects.count(),
        "groups": TestGroup.objects.count(),
        "sessions_total": agg["total"] or 0,
        "sessions_finished": agg["finished"] or 0,
        "sessions_active": agg["active"] or 0,
        "sessions_cancelled": agg["cancelled"] or 0,
        "sessions_solo": agg["solo"] or 0,
        "sessions_group": agg["group"] or 0,
    }


def recent_sessions(limit=12):
    return list(
        QuizSession.objects.select_related("subtest", "subtest__test", "user")
        .order_by("-started_at")[:limit]
    )


def top_users(limit=8):
    """Eng faol foydalanuvchilar (solo urinishlar bo'yicha)."""
    return list(
        TelegramUser.objects.annotate(
            attempts=Count("sessions", filter=Q(sessions__mode=SOLO)),
            finished=Count(
                "sessions",
                filter=Q(sessions__mode=SOLO, sessions__status=FINISHED),
            ),
        )
        .filter(attempts__gt=0)
        .order_by("-attempts")[:limit]
    )


def users_with_kpi(search="", order="-last_at"):
    qs = TelegramUser.objects.annotate(
        attempts=Count("sessions", filter=Q(sessions__mode=SOLO), distinct=True),
        finished=Count(
            "sessions",
            filter=Q(sessions__mode=SOLO, sessions__status=FINISHED),
            distinct=True,
        ),
        last_at=Max("sessions__started_at"),
    )
    if search:
        qs = qs.filter(
            Q(full_name__icontains=search)
            | Q(username__icontains=search)
            | Q(phone__icontains=search)
        )
    allowed = {"-last_at", "last_at", "-attempts", "attempts", "full_name"}
    if order not in allowed:
        order = "-last_at"
    # last_at None'larni oxiriga surish uchun F bilan tartiblash
    return qs.order_by(F("last_at").desc(nulls_last=True)) if order == "-last_at" else qs.order_by(order)


def user_kpi(user):
    """Bitta foydalanuvchi uchun to'liq KPI."""
    solo = QuizSession.objects.filter(user=user, mode=SOLO)
    solo_agg = solo.aggregate(
        attempts=Count("id"),
        finished=Count("id", filter=Q(status=FINISHED)),
        active=Count("id", filter=Q(status=ACTIVE)),
        cancelled=Count("id", filter=Q(status=CANCELLED)),
    )

    # Yakunlangan solo sessiyalar bo'yicha o'rtacha foiz
    finished_qs = solo.filter(status=FINISHED, total__gt=0).annotate(
        pct=Cast(F("score"), FloatField()) * 100.0 / Cast(F("total"), FloatField())
    )
    avg_pct = finished_qs.aggregate(v=Avg("pct"))["v"]

    # Barcha javoblar (solo + guruh) bo'yicha aniqlik
    ans = Answer.objects.filter(user=user).aggregate(
        total=Count("id"),
        correct=Count("id", filter=Q(is_correct=True)),
    )
    total_ans = ans["total"] or 0
    correct_ans = ans["correct"] or 0
    accuracy = round(correct_ans * 100.0 / total_ans, 1) if total_ans else None

    # Guruh testlarida qatnashganlar (javob bergan sessiyalar)
    group_participated = (
        Answer.objects.filter(user=user, session__mode=GROUP)
        .values("session_id")
        .distinct()
        .count()
    )

    # Qism bo'yicha taqsimot: qaysi guruh, nechta urinish, qayerda yakunlagan
    breakdown = list(
        solo.values("subtest__test_id", "subtest__test__name", "subtest__name")
        .annotate(
            attempts=Count("id"),
            finished=Count("id", filter=Q(status=FINISHED)),
            best=Max("score"),
            total=Max("total"),
        )
        .order_by("subtest__test__name", "-attempts")
    )
    # Har bir testning tegishli guruhlari (bir test bir nechta guruhda bo'lishi mumkin)
    test_ids = {b["subtest__test_id"] for b in breakdown}
    groups_map = {}
    if test_ids:
        for row in TestGroup.objects.filter(tests__id__in=test_ids).values(
            "tests__id", "name"
        ):
            groups_map.setdefault(row["tests__id"], []).append(row["name"])
    for b in breakdown:
        b["groups"] = groups_map.get(b["subtest__test_id"], [])

    recent = list(
        solo.select_related("subtest", "subtest__test").order_by("-started_at")[:15]
    )

    return {
        "attempts": solo_agg["attempts"] or 0,
        "finished": solo_agg["finished"] or 0,
        "active": solo_agg["active"] or 0,
        "cancelled": solo_agg["cancelled"] or 0,
        "avg_pct": round(avg_pct, 1) if avg_pct is not None else None,
        "total_answers": total_ans,
        "correct_answers": correct_ans,
        "accuracy": accuracy,
        "group_participated": group_participated,
        "breakdown": breakdown,
        "recent": recent,
    }
