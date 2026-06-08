import os
import tempfile

import openpyxl
from django.test import SimpleTestCase

from quiz.parsers.excel_parser import parse_excel
from quiz.parsers.text_parser import parse_text


class ParserTests(SimpleTestCase):
    def test_excel_correct_index_does_not_shift_when_option_is_blank(self):
        handle, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(handle)
        try:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.append([
                "Test",
                "SubTest",
                "Question",
                "Option1",
                "Option2",
                "Option3",
                "Option4",
                "Correct",
            ])
            sheet.append([
                "T",
                "S",
                "Q",
                "A",
                "",
                "C",
                "D",
                3,
            ])
            workbook.save(path)
            workbook.close()

            question = parse_excel(path)[0]["questions"][0]
            self.assertEqual(
                [
                    (option["text"], option["is_correct"])
                    for option in question["options"]
                ],
                [("A", False), ("C", True), ("D", False)],
            )
        finally:
            os.remove(path)

    def test_text_parser_marks_multiple_correct_answers_for_review(self):
        questions = parse_text("? Savol\n+ A\n+ B\n= C")

        self.assertEqual(len(questions), 1)
        self.assertTrue(questions[0]["needs_review"])

    def test_text_parser_ignores_empty_question_and_option(self):
        questions = parse_text("?\n+ A\n? Savol\n+\n= B\n+ C")

        self.assertEqual(len(questions), 1)
        self.assertEqual(
            [option["text"] for option in questions[0]["options"]],
            ["B", "C"],
        )

