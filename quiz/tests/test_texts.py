from django.test import SimpleTestCase

from bot import texts


class TextFormatterTests(SimpleTestCase):
    def test_answered_question_text_marks_correct_answer(self):
        message = texts.answered_question_text(
            0,
            5,
            "2 < 3?",
            "Ha <ok>",
            "Ha <ok>",
            True,
        )

        self.assertIn("🟢 <b>TO'G'RI</b>", message)
        self.assertIn("2 &lt; 3?", message)
        self.assertIn("Ha &lt;ok&gt;", message)
        self.assertLessEqual(len(message), 4096)

    def test_answered_question_text_marks_wrong_answer(self):
        message = texts.answered_question_text(
            1,
            5,
            "Savol",
            "A",
            "B",
            False,
        )

        self.assertIn("🔴 <b>XATO</b>", message)
        self.assertIn("🟢 <b>To'g'ri javob:</b> B", message)

    def test_answered_question_text_keeps_telegram_limit(self):
        message = texts.answered_question_text(
            0,
            1,
            "<" * 10000,
            "<" * 1000,
            ">" * 1000,
            False,
        )

        self.assertLessEqual(len(message), 4096)

