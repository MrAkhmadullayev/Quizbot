from django.test import TestCase

from quiz import services
from quiz.models import Question


def question_data(text="Savol"):
    return {
        "text": text,
        "needs_review": False,
        "options": [
            {"text": "A", "is_correct": True},
            {"text": "B", "is_correct": False},
        ],
    }


class ServiceTests(TestCase):
    def test_unresolved_question_is_rejected(self):
        data = question_data()
        data["options"][0]["is_correct"] = False

        with self.assertRaises(ValueError):
            services.save_questions("Test", "Qism", [data])

        self.assertFalse(Question.objects.exists())

    def test_duplicate_import_is_skipped(self):
        first = services.save_questions(
            "Test",
            "Qism",
            [question_data()],
        )
        second = services.save_questions(
            "Test",
            "Qism",
            [question_data()],
        )

        self.assertEqual(first["questions_created"], 1)
        self.assertEqual(second["questions_created"], 0)
        self.assertEqual(second["questions_skipped"], 1)
        self.assertEqual(Question.objects.count(), 1)

    def test_one_option_question_is_rejected(self):
        data = question_data()
        data["options"] = [data["options"][0]]

        errors = services.validate_questions([data])

        self.assertTrue(errors)

    def test_empty_group_is_rejected(self):
        errors = services.validate_groups([
            {"test": "Test", "subtest": "Qism", "questions": []}
        ])

        self.assertTrue(errors)
