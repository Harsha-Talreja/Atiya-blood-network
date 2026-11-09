from datetime import date, timedelta

from django.test import SimpleTestCase

from donors.eligibility import cooldown_progress

TODAY = date(2026, 6, 15)


class CooldownProgressTests(SimpleTestCase):
    def test_never_donated_is_ready(self):
        self.assertEqual(cooldown_progress(None, today=TODAY), 100)

    def test_donated_today_is_zero_percent(self):
        self.assertEqual(cooldown_progress(TODAY, today=TODAY), 0)

    def test_halfway_through_is_fifty_percent(self):
        self.assertEqual(cooldown_progress(TODAY - timedelta(days=45), today=TODAY), 50)

    def test_day_89_is_almost_ready_but_not_ready(self):
        self.assertEqual(cooldown_progress(TODAY - timedelta(days=89), today=TODAY), 99)

    def test_day_90_and_later_is_ready(self):
        for days in (90, 91, 400):
            with self.subTest(days=days):
                self.assertEqual(cooldown_progress(TODAY - timedelta(days=days), today=TODAY), 100)

    def test_a_date_in_the_future_never_gives_a_negative_value(self):
        self.assertEqual(cooldown_progress(TODAY + timedelta(days=10), today=TODAY), 0)
