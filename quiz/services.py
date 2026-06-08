"""Parse qilingan testlarni validatsiya qilish va bazaga saqlash."""
from django.conf import settings
from django.db import transaction
from django.db.models import Max

from quiz.models import Option, Question, SubTest, Test

MIN_OPTIONS = 2
MAX_OPTIONS = 10


def validate_questions(questions, require_correct=True):
    errors = []
    for index, question in enumerate(questions, start=1):
        text = str(question.get("text", "")).strip()
        options = question.get("options") or []
        correct_count = sum(
            bool(option.get("is_correct"))
            for option in options
        )

        if not text:
            errors.append(f"{index}-savol matni bo'sh.")
        if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
            errors.append(
                f"{index}-savolda variantlar soni "
                f"{MIN_OPTIONS}–{MAX_OPTIONS} oralig'ida bo'lishi kerak."
            )
        if any(not str(option.get("text", "")).strip() for option in options):
            errors.append(f"{index}-savolda bo'sh variant bor.")
        if require_correct and correct_count != 1:
            errors.append(
                f"{index}-savolda aynan bitta to'g'ri javob bo'lishi kerak."
            )
    return errors


def validate_groups(groups, require_correct=True):
    errors = []
    if not groups:
        return ["Saqlash uchun test ma'lumoti topilmadi."]

    for group_index, group in enumerate(groups, start=1):
        test_name = str(group.get("test", "")).strip() or "Nomsiz test"
        subtest_name = str(group.get("subtest", "")).strip() or "1-qism"
        questions = group.get("questions") or []
        if len(test_name) > 255:
            errors.append(f"{group_index}-guruh test nomi 255 belgidan uzun.")
        if len(subtest_name) > 255:
            errors.append(f"{group_index}-guruh qism nomi 255 belgidan uzun.")
        if not questions:
            errors.append(
                f"{test_name} / {subtest_name}: savollar topilmadi."
            )
        question_errors = validate_questions(
            questions,
            require_correct=require_correct,
        )
        errors.extend(
            f"{test_name} / {subtest_name}: {error}"
            for error in question_errors
        )
    return errors


@transaction.atomic
def save_questions(test_name, subtest_name, questions):
    if not questions:
        raise ValueError("Saqlash uchun savollar topilmadi.")
    errors = validate_questions(questions)
    if errors:
        raise ValueError(" ".join(errors[:10]))

    test_name = test_name.strip() or "Nomsiz test"
    subtest_name = subtest_name.strip() or "1-qism"
    test, _ = Test.objects.get_or_create(name=test_name)

    per_part = max(1, settings.QUESTIONS_PER_PART)
    chunks = [
        questions[index:index + per_part]
        for index in range(0, len(questions), per_part)
    ]
    if not chunks:
        chunks = [[]]

    created_subtests = []
    created_questions = 0
    skipped_questions = 0
    split = len(chunks) > 1

    for chunk_index, chunk in enumerate(chunks, start=1):
        name = (
            f"{subtest_name} ({chunk_index}-qism)"
            if split
            else subtest_name
        )
        subtest = _get_or_create_subtest(test, name)
        created_subtests.append(subtest)
        created, skipped = _create_questions(subtest, chunk)
        created_questions += created
        skipped_questions += skipped

    return {
        "test": test,
        "subtests": created_subtests,
        "questions_created": created_questions,
        "questions_skipped": skipped_questions,
        "needs_review": 0,
    }


def _get_or_create_subtest(test, name):
    subtest = SubTest.objects.filter(test=test, name=name).first()
    if subtest:
        return subtest
    max_order = SubTest.objects.filter(test=test).aggregate(
        max_order=Max("order")
    )["max_order"]
    next_order = 0 if max_order is None else max_order + 1
    return SubTest.objects.create(
        test=test,
        name=name,
        order=next_order,
    )


def _create_questions(subtest, questions):
    existing_texts = set(
        subtest.questions.values_list("text", flat=True)
    )
    new_data = []
    seen_texts = set(existing_texts)
    for question in questions:
        text = question["text"].strip()
        if text in seen_texts:
            continue
        seen_texts.add(text)
        new_data.append(question)
    skipped = len(questions) - len(new_data)
    if not new_data:
        return 0, skipped

    max_order = subtest.questions.aggregate(
        max_order=Max("order")
    )["max_order"]
    next_order = 0 if max_order is None else max_order + 1
    question_models = [
        Question(
            subtest=subtest,
            text=data["text"].strip(),
            order=next_order + offset,
            needs_review=False,
        )
        for offset, data in enumerate(new_data)
    ]
    Question.objects.bulk_create(question_models)

    option_models = []
    for question, data in zip(question_models, new_data):
        option_models.extend(
            Option(
                question=question,
                text=option["text"].strip(),
                is_correct=bool(option["is_correct"]),
                order=order,
            )
            for order, option in enumerate(data["options"])
        )
    Option.objects.bulk_create(option_models)
    return len(question_models), skipped


@transaction.atomic
def save_grouped(groups):
    errors = validate_groups(groups)
    if errors:
        raise ValueError(" ".join(errors[:20]))
    return [
        save_questions(
            group["test"],
            group["subtest"],
            group["questions"],
        )
        for group in groups
    ]
