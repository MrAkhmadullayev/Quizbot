"""Django ORM bilan xavfsiz async ishlash uchun yordamchilar."""
import functools

from asgiref.sync import sync_to_async
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from quiz.models import (
    Answer,
    GroupPoll,
    KnownGroup,
    Option,
    Question,
    QuizSession,
    SubTest,
    TelegramUser,
    Test,
    TestGroup,
)


class QuizOperationError(Exception):
    """Foydalanuvchiga ko'rsatish mumkin bo'lgan quiz operatsiyasi xatosi."""


def db_task(func):
    """Sync ORM funksiyani thread-pool'da ishlaydigan async funksiyaga o'raydi.

    thread_sensitive=False — har bir chaqiruv pooldagi alohida ishchi
    thread'da bajariladi. thread_sensitive=True bo'lsa BARCHA so'rovlar
    bitta umumiy thread orqali navbatga tushadi va yuk ostida bot qotadi.
    Har bir funksiya o'z ichida yaxlit (bitta tranzaksiya) bo'lgani uchun
    parallel bajarish xavfsiz.

    close_old_connections — har thread eskirgan/yaroqsiz DB ulanishini
    qayta ishlatmasligi uchun chaqiruvdan oldin va keyin tozalaydi.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()
    return sync_to_async(wrapper, thread_sensitive=False)


def _clip(value, limit):
    """Postgres'da varchar limitidan oshib xato bermasligi uchun kesadi."""
    if value is None:
        return None
    return str(value)[:limit]


def _playable_questions(subtest_id=None):
    queryset = (
        Question.objects.filter(needs_review=False)
        .annotate(
            option_count=Count("options"),
            correct_count=Count(
                "options",
                filter=Q(options__is_correct=True),
            ),
        )
        .filter(option_count__gte=2, correct_count=1)
        .order_by("order", "id")
    )
    if subtest_id is not None:
        queryset = queryset.filter(subtest_id=subtest_id)
    return queryset


def _registered_user(user_id):
    return TelegramUser.objects.filter(id=user_id).exclude(phone="").first()


# ---------------- Foydalanuvchi ----------------
@db_task
def get_user(tg_id):
    return TelegramUser.objects.filter(tg_id=tg_id).first()


@db_task
def create_user(tg_id, username, full_name, phone):
    user, _ = TelegramUser.objects.update_or_create(
        tg_id=tg_id,
        defaults={
            "username": _clip(username, 255),
            "full_name": _clip(full_name, 255) or "",
            "phone": _clip(phone, 32) or "",
        },
    )
    return user


# ---------------- Guruhlar ----------------
def _playable_test_qs():
    """Ishlashga tayyor savoli bo'lgan faol testlar queryset'i."""
    playable = _playable_questions().filter(
        subtest__test_id=OuterRef("pk"),
        subtest__is_active=True,
    )
    return (
        Test.objects.filter(is_active=True)
        .annotate(has_playable=Exists(playable))
        .filter(has_playable=True)
    )


@db_task
def list_groups():
    """Ishlashga tayyor testi bor faol guruhlar."""
    playable_ids = _playable_test_qs().values_list("id", flat=True)
    return list(
        TestGroup.objects.filter(is_active=True, tests__in=playable_ids)
        .distinct()
        .order_by("order", "name")
    )


@db_task
def get_group(group_id):
    return TestGroup.objects.filter(id=group_id, is_active=True).first()


@db_task
def list_group_tests(group_id):
    """Tanlangan guruhga biriktirilgan, ishlashga tayyor testlar."""
    return list(
        _playable_test_qs().filter(groups__id=group_id).distinct()
    )


# ---------------- Testlar ----------------
@db_task
def list_tests():
    return list(_playable_test_qs())


@db_task
def list_subtests(test_id):
    subtests = list(
        SubTest.objects.filter(
            test_id=test_id,
            test__is_active=True,
            is_active=True,
        )
    )
    # Savol matnlarini yuklamasdan faqat sonini olamiz (yengil so'rov)
    playable_ids = _playable_questions().filter(
        subtest__test_id=test_id
    ).values_list("id", flat=True)
    counts = dict(
        Question.objects.filter(id__in=playable_ids)
        .values_list("subtest_id")
        .annotate(total=Count("id"))
        .values_list("subtest_id", "total")
    )
    result = []
    for subtest in subtests:
        subtest.question_total = counts.get(subtest.id, 0)
        if subtest.question_total:
            result.append(subtest)
    return result


@db_task
def get_subtest(subtest_id):
    return (
        SubTest.objects.select_related("test")
        .filter(id=subtest_id, is_active=True, test__is_active=True)
        .first()
    )


@db_task
def subtest_question_count(subtest_id):
    return _playable_questions(subtest_id).count()


def _session_question(session, index):
    if index < 0 or index >= len(session.question_ids):
        return None
    question = (
        Question.objects.filter(
            id=session.question_ids[index],
            subtest_id=session.subtest_id,
        )
        .prefetch_related("options")
        .first()
    )
    if not question:
        return None
    options = list(question.options.all())
    if not 2 <= len(options) <= 10:
        return None
    if sum(option.is_correct for option in options) != 1:
        return None
    return {
        "question": question,
        "options": options,
    }


@db_task
def get_session_question(session_id, index):
    session = QuizSession.objects.filter(id=session_id).first()
    if not session:
        return None
    return _session_question(session, index)


# ---------------- Sessiyalar ----------------
@db_task
@transaction.atomic
def create_session(user_id, subtest_id, mode, chat_id=None):
    user = _registered_user(user_id)
    if not user:
        raise QuizOperationError("Avval telefon raqamingiz bilan ro'yxatdan o'ting.")

    subtest = (
        SubTest.objects.select_related("test")
        .filter(id=subtest_id, is_active=True, test__is_active=True)
        .first()
    )
    if not subtest:
        raise QuizOperationError("Bu test qismi topilmadi yoki faol emas.")

    if mode not in {QuizSession.SOLO, QuizSession.GROUP}:
        raise QuizOperationError("Noto'g'ri test rejimi.")
    if mode == QuizSession.SOLO and chat_id is not None:
        raise QuizOperationError("Yakka rejim uchun guruh tanlanmaydi.")
    if mode == QuizSession.GROUP:
        group_exists = KnownGroup.objects.filter(
            chat_id=chat_id,
            added_by_id=user_id,
            is_active=True,
        ).exists()
        if not group_exists:
            raise QuizOperationError("Bu guruh sizga tegishli emas yoki bot guruhdan chiqarilgan.")

    question_ids = list(
        _playable_questions(subtest_id).values_list("id", flat=True)
    )
    if not question_ids:
        raise QuizOperationError("Bu qismda tayyor savollar yo'q.")

    return QuizSession.objects.create(
        user=user,
        subtest=subtest,
        mode=mode,
        chat_id=chat_id,
        total=len(question_ids),
        question_ids=question_ids,
    )


@db_task
def get_session(session_id):
    return (
        QuizSession.objects.select_related("subtest", "user")
        .filter(id=session_id)
        .first()
    )


@db_task
@transaction.atomic
def record_solo_answer(session_id, option_id, tg_id):
    session = (
        QuizSession.objects.select_for_update()
        .select_related("user")
        .filter(id=session_id)
        .first()
    )
    if not session or session.mode != QuizSession.SOLO:
        raise QuizOperationError("Yakka test sessiyasi topilmadi.")
    if session.user.tg_id != tg_id:
        raise QuizOperationError("Bu test sessiyasi sizga tegishli emas.")
    if session.status != QuizSession.ACTIVE:
        raise QuizOperationError("Bu test allaqachon yakunlangan.")

    question_index = session.current_index
    data = _session_question(session, question_index)
    if not data:
        raise QuizOperationError("Joriy savol topilmadi.")
    question = data["question"]

    # Variantlar _session_question'da yuklangan — qo'shimcha so'rov kerak emas
    options = data["options"]
    selected = next((opt for opt in options if opt.id == option_id), None)
    if not selected:
        raise QuizOperationError("Bu tugma eskirgan. Joriy savolga javob bering.")

    correct = next((opt for opt in options if opt.is_correct), None)
    if not correct:
        raise QuizOperationError("Savolning to'g'ri javobi belgilanmagan.")

    is_correct = selected.id == correct.id
    try:
        Answer.objects.create(
            session=session,
            question=question,
            selected=selected,
            is_correct=is_correct,
            user=session.user,
        )
    except IntegrityError as exc:
        raise QuizOperationError("Bu savolga javob allaqachon qabul qilingan.") from exc

    session.current_index += 1
    if is_correct:
        session.score += 1

    finished = session.current_index >= session.total
    update_fields = ["score", "current_index"]
    if finished:
        session.status = QuizSession.FINISHED
        session.finished_at = timezone.now()
        update_fields.extend(["status", "finished_at"])
    session.save(update_fields=update_fields)

    return {
        "is_correct": is_correct,
        "question_index": question_index,
        "question_text": question.text,
        "selected_text": selected.text,
        "correct_text": correct.text,
        "finished": finished,
        "next_index": session.current_index,
        "score": session.score,
        "total": session.total,
    }


@db_task
@transaction.atomic
def finish_solo_session(session_id, tg_id):
    session = (
        QuizSession.objects.select_for_update()
        .select_related("user")
        .filter(id=session_id)
        .first()
    )
    if not session or session.mode != QuizSession.SOLO:
        raise QuizOperationError("Yakka test sessiyasi topilmadi.")
    if session.user.tg_id != tg_id:
        raise QuizOperationError("Bu test sessiyasi sizga tegishli emas.")
    if session.status == QuizSession.ACTIVE:
        session.status = QuizSession.FINISHED
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at"])
    return {"score": session.score, "total": session.total}


@db_task
def user_history(user_id, limit=10):
    solo = list(
        QuizSession.objects.select_related("subtest", "subtest__test")
        .filter(user_id=user_id, mode=QuizSession.SOLO)
        .order_by("-started_at")[:limit]
    )

    # Faqat eng so'nggi `limit` ta guruh sessiyasi (chegarasiz yuklamaslik uchun)
    group_ids = list(
        QuizSession.objects.filter(
            Q(user_id=user_id) | Q(answers__user_id=user_id),
            mode=QuizSession.GROUP,
        )
        .order_by("-started_at")
        .distinct()
        .values_list("id", flat=True)[:limit]
    )
    groups = list(
        QuizSession.objects.select_related("subtest", "subtest__test")
        .filter(id__in=group_ids)
        .annotate(
            user_score=Count(
                "answers",
                filter=Q(answers__user_id=user_id, answers__is_correct=True),
            ),
            user_total=Count(
                "answers",
                filter=Q(answers__user_id=user_id),
            ),
        )
    )

    rows = [
        {
            "test_name": session.subtest.test.name,
            "subtest_name": session.subtest.name,
            "score": session.score,
            "total": session.total,
            "status": session.status,
            "mode": session.mode,
            "started_at": session.started_at,
        }
        for session in solo
    ]
    rows.extend(
        {
            "test_name": session.subtest.test.name,
            "subtest_name": session.subtest.name,
            "score": session.user_score,
            "total": session.user_total,
            "status": session.status,
            "mode": session.mode,
            "started_at": session.started_at,
        }
        for session in groups
    )
    rows.sort(key=lambda row: row["started_at"], reverse=True)
    return rows[:limit]


# ---------------- Guruh ----------------
@db_task
def get_group_control(session_id, tg_id):
    session = (
        QuizSession.objects.select_related("user")
        .filter(id=session_id, mode=QuizSession.GROUP)
        .first()
    )
    if not session:
        raise QuizOperationError("Guruh test sessiyasi topilmadi.")
    if session.user.tg_id != tg_id:
        raise QuizOperationError("Faqat testni boshlagan inson boshqara oladi.")
    data = _session_question(session, session.current_index)
    return {
        "id": session.id,
        "chat_id": session.chat_id,
        "current_index": session.current_index,
        "current_question_id": data["question"].id if data else None,
        "total": session.total,
        "status": session.status,
    }


@db_task
def prepare_group_question(session_id, index):
    session = QuizSession.objects.filter(
        id=session_id,
        mode=QuizSession.GROUP,
        status=QuizSession.ACTIVE,
    ).first()
    if not session:
        raise QuizOperationError("Guruh testi faol emas.")

    data = _session_question(session, index)
    if not data:
        return None

    question = data["question"]
    options = data["options"]
    correct_index = next(
        (i for i, option in enumerate(options) if option.is_correct),
        None,
    )
    if correct_index is None:
        raise QuizOperationError("Savolning to'g'ri javobi belgilanmagan.")

    return {
        "chat_id": session.chat_id,
        "total": session.total,
        "question": question,
        "options": options,
        "correct_index": correct_index,
    }


@db_task
@transaction.atomic
def save_group_poll(poll_id, message_id, session_id, question_id, option_map, index):
    session = (
        QuizSession.objects.select_for_update()
        .filter(
            id=session_id,
            mode=QuizSession.GROUP,
            status=QuizSession.ACTIVE,
        )
        .first()
    )
    if not session:
        raise QuizOperationError("Guruh testi faol emas.")

    expected = _session_question(session, index)
    if not expected or expected["question"].id != question_id:
        raise QuizOperationError("Poll savoli sessiya holatiga mos emas.")

    try:
        poll = GroupPoll.objects.create(
            poll_id=poll_id,
            message_id=message_id,
            session=session,
            question_id=question_id,
            option_map=option_map,
        )
    except IntegrityError as exc:
        raise QuizOperationError("Bu savol uchun poll allaqachon yuborilgan.") from exc

    session.current_index = index
    session.save(update_fields=["current_index"])
    return poll


@db_task
@transaction.atomic
def close_group_poll(session_id, question_id):
    poll = (
        GroupPoll.objects.select_for_update()
        .select_related("session")
        .filter(
            session_id=session_id,
            question_id=question_id,
            is_closed=False,
        )
        .first()
    )
    if not poll:
        return None
    poll.is_closed = True
    poll.closed_at = timezone.now()
    poll.save(update_fields=["is_closed", "closed_at"])
    return {
        "poll_id": poll.poll_id,
        "chat_id": poll.session.chat_id,
        "message_id": poll.message_id,
    }


@db_task
@transaction.atomic
def record_group_answer(poll_id, option_index, tg_id, username, full_name):
    poll = (
        GroupPoll.objects.select_for_update()
        .select_related("session", "question")
        .filter(poll_id=poll_id)
        .first()
    )
    if not poll or poll.is_closed or poll.session.status != QuizSession.ACTIVE:
        return None

    option_id = poll.option_map.get(str(option_index))
    options = list(Option.objects.filter(question=poll.question))
    selected = next((opt for opt in options if opt.id == option_id), None)
    if not selected:
        return None

    correct = next((opt for opt in options if opt.is_correct), None)
    if not correct:
        return None

    user, _ = TelegramUser.objects.update_or_create(
        tg_id=tg_id,
        defaults={
            "username": _clip(username, 255),
            "full_name": _clip(full_name, 255) or "",
        },
    )
    answer, _ = Answer.objects.update_or_create(
        session=poll.session,
        question=poll.question,
        user=user,
        defaults={
            "selected": selected,
            "is_correct": selected.id == correct.id,
        },
    )
    return {"is_correct": answer.is_correct, "user_id": user.id}


@db_task
def group_leaderboard(session_id):
    rows = (
        Answer.objects.filter(session_id=session_id, user__isnull=False)
        .values("user__full_name", "user__username", "user__tg_id")
        .annotate(
            correct=Count("id", filter=Q(is_correct=True)),
            total=Count("id"),
        )
        .order_by("-correct", "-total", "user__full_name")
    )
    return list(rows)


@db_task
@transaction.atomic
def finish_group_session(session_id, tg_id):
    session = (
        QuizSession.objects.select_for_update()
        .select_related("user")
        .filter(id=session_id, mode=QuizSession.GROUP)
        .first()
    )
    if not session:
        raise QuizOperationError("Guruh test sessiyasi topilmadi.")
    if session.user.tg_id != tg_id:
        raise QuizOperationError("Faqat testni boshlagan inson boshqara oladi.")
    if session.status == QuizSession.ACTIVE:
        session.status = QuizSession.FINISHED
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at"])
    GroupPoll.objects.filter(session=session, is_closed=False).update(
        is_closed=True,
        closed_at=timezone.now(),
    )
    return {"chat_id": session.chat_id}


@db_task
@transaction.atomic
def cancel_session(session_id):
    QuizSession.objects.filter(
        id=session_id,
        status=QuizSession.ACTIVE,
    ).update(
        status=QuizSession.CANCELLED,
        finished_at=timezone.now(),
    )


@db_task
def register_group(chat_id, title, added_by_tg_id):
    user = (
        TelegramUser.objects.filter(tg_id=added_by_tg_id)
        .exclude(phone="")
        .first()
        if added_by_tg_id
        else None
    )
    KnownGroup.objects.update_or_create(
        chat_id=chat_id,
        defaults={
            "title": _clip(title, 255) or "",
            "added_by": user,
            "is_active": True,
        },
    )


@db_task
def deactivate_group(chat_id):
    KnownGroup.objects.filter(chat_id=chat_id).update(is_active=False)


@db_task
def list_user_groups(user_id):
    return list(
        KnownGroup.objects.filter(
            is_active=True,
            added_by_id=user_id,
        )
    )
