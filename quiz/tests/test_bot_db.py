from asgiref.sync import async_to_sync
from django.test import TransactionTestCase

from bot import db
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
)


class BotDatabaseTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = TelegramUser.objects.create(
            tg_id=100,
            full_name="Owner",
            phone="+998901234567",
        )
        self.other = TelegramUser.objects.create(
            tg_id=200,
            full_name="Other",
            phone="+998901234568",
        )
        self.test = Test.objects.create(name="Test")
        self.subtest = SubTest.objects.create(
            test=self.test,
            name="Qism",
        )
        self.question1, self.correct1, self.wrong1 = self._question(
            "Savol 1",
            0,
        )
        self.question2, self.correct2, self.wrong2 = self._question(
            "Savol 2",
            1,
        )

    def _question(self, text, order):
        question = Question.objects.create(
            subtest=self.subtest,
            text=text,
            order=order,
        )
        correct = Option.objects.create(
            question=question,
            text="To'g'ri",
            is_correct=True,
            order=0,
        )
        wrong = Option.objects.create(
            question=question,
            text="Noto'g'ri",
            order=1,
        )
        return question, correct, wrong

    def _solo_session(self):
        return async_to_sync(db.create_session)(
            self.user.id,
            self.subtest.id,
            "solo",
        )

    def _group_session(self):
        KnownGroup.objects.create(
            chat_id=-1001,
            title="Guruh",
            added_by=self.user,
        )
        return async_to_sync(db.create_session)(
            self.user.id,
            self.subtest.id,
            "group",
            chat_id=-1001,
        )

    def test_stale_double_click_does_not_create_second_answer(self):
        session = self._solo_session()
        async_to_sync(db.record_solo_answer)(
            session.id,
            self.correct1.id,
            self.user.tg_id,
        )

        with self.assertRaises(db.QuizOperationError):
            async_to_sync(db.record_solo_answer)(
                session.id,
                self.correct1.id,
                self.user.tg_id,
            )

        session.refresh_from_db()
        self.assertEqual(session.score, 1)
        self.assertEqual(session.current_index, 1)
        self.assertEqual(Answer.objects.filter(session=session).count(), 1)

    def test_option_from_another_question_is_rejected(self):
        session = self._solo_session()

        with self.assertRaises(db.QuizOperationError):
            async_to_sync(db.record_solo_answer)(
                session.id,
                self.correct2.id,
                self.user.tg_id,
            )

        self.assertFalse(Answer.objects.filter(session=session).exists())

    def test_solo_answer_returns_feedback_payload(self):
        session = self._solo_session()

        result = async_to_sync(db.record_solo_answer)(
            session.id,
            self.correct1.id,
            self.user.tg_id,
        )

        self.assertEqual(result["question_index"], 0)
        self.assertEqual(result["question_text"], self.question1.text)
        self.assertEqual(result["selected_text"], self.correct1.text)
        self.assertEqual(result["correct_text"], self.correct1.text)

    def test_other_user_cannot_answer_or_finish_solo_session(self):
        session = self._solo_session()

        with self.assertRaises(db.QuizOperationError):
            async_to_sync(db.record_solo_answer)(
                session.id,
                self.correct1.id,
                self.other.tg_id,
            )
        with self.assertRaises(db.QuizOperationError):
            async_to_sync(db.finish_solo_session)(
                session.id,
                self.other.tg_id,
            )

    def test_closed_group_poll_ignores_late_answer(self):
        session = self._group_session()
        group_poll = async_to_sync(db.save_group_poll)(
            "poll-1",
            10,
            session.id,
            self.question1.id,
            {"0": self.correct1.id, "1": self.wrong1.id},
            0,
        )
        async_to_sync(db.close_group_poll)(
            session.id,
            self.question1.id,
        )

        result = async_to_sync(db.record_group_answer)(
            "poll-1",
            0,
            300,
            "guest",
            "Guest",
        )

        self.assertIsNone(result)
        self.assertFalse(Answer.objects.filter(session=session).exists())

    def test_repeated_group_update_is_idempotent(self):
        session = self._group_session()
        async_to_sync(db.save_group_poll)(
            "poll-1",
            10,
            session.id,
            self.question1.id,
            {"0": self.correct1.id, "1": self.wrong1.id},
            0,
        )

        for _ in range(2):
            async_to_sync(db.record_group_answer)(
                "poll-1",
                0,
                300,
                "guest",
                "Guest",
            )

        self.assertEqual(Answer.objects.filter(session=session).count(), 1)

    def test_unreviewed_question_is_not_playable(self):
        invalid = Question.objects.create(
            subtest=self.subtest,
            text="Tekshirilmagan",
            order=2,
            needs_review=True,
        )
        Option.objects.create(
            question=invalid,
            text="A",
            order=0,
        )
        Option.objects.create(
            question=invalid,
            text="B",
            order=1,
        )

        count = async_to_sync(db.subtest_question_count)(self.subtest.id)

        self.assertEqual(count, 2)

    def test_session_uses_question_snapshot(self):
        session = self._solo_session()
        self.question1.needs_review = True
        self.question1.save(update_fields=["needs_review"])

        data = async_to_sync(db.get_session_question)(session.id, 0)

        self.assertEqual(data["question"].id, self.question1.id)
