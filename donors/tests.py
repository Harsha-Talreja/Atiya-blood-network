from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import Location
from donors import eligibility
from donors.models import DonorProfile

TODAY = date(2026, 6, 15)  # fixed date -> these tests never depend on the real clock


class EligibilityFunctionTests(SimpleTestCase):
    def test_no_donation_date_is_eligible(self):
        self.assertTrue(eligibility.is_eligible(None, today=TODAY))
        self.assertIsNone(eligibility.next_eligible_date(None))
        self.assertEqual(eligibility.days_until_eligible(None, today=TODAY), 0)

    def test_89_days_ago_is_not_eligible(self):
        last = TODAY - timedelta(days=89)
        self.assertFalse(eligibility.is_eligible(last, today=TODAY))
        self.assertEqual(eligibility.days_until_eligible(last, today=TODAY), 1)

    def test_90_days_ago_is_eligible(self):
        last = TODAY - timedelta(days=90)
        self.assertTrue(eligibility.is_eligible(last, today=TODAY))
        self.assertEqual(eligibility.days_until_eligible(last, today=TODAY), 0)

    def test_91_days_ago_is_eligible(self):
        self.assertTrue(eligibility.is_eligible(TODAY - timedelta(days=91), today=TODAY))

    def test_next_eligible_date_is_last_plus_90_days(self):
        self.assertEqual(
            eligibility.next_eligible_date(date(2026, 1, 1)), date(2026, 4, 1)
        )

    def test_cutoff_is_today_minus_90_days(self):
        self.assertEqual(eligibility.eligibility_cutoff(today=TODAY), TODAY - timedelta(days=90))


class DonorProfileModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="donor1")
        self.location, _ = Location.objects.get_or_create(city="Sukkur", area="Military Road")

    def make_profile(self, days_ago=None, **overrides):
        last = None if days_ago is None else timezone.localdate() - timedelta(days=days_ago)
        data = dict(
            user=self.user, full_name="Ali Khan", phone="03001234567",
            blood_type="O+", location=self.location, last_donation_date=last,
        )
        data.update(overrides)
        return DonorProfile(**data)

    def test_no_donation_date_is_eligible(self):
        profile = self.make_profile(days_ago=None)
        self.assertTrue(profile.is_eligible)
        self.assertIsNone(profile.next_eligible_date)
        self.assertEqual(profile.days_until_eligible, 0)

    def test_89_days_not_eligible(self):
        profile = self.make_profile(days_ago=89)
        self.assertFalse(profile.is_eligible)
        self.assertEqual(profile.days_until_eligible, 1)

    def test_90_days_eligible(self):
        profile = self.make_profile(days_ago=90)
        self.assertTrue(profile.is_eligible)
        self.assertEqual(profile.days_until_eligible, 0)

    def test_new_profile_is_available_by_default(self):
        self.assertTrue(self.make_profile().is_available)

    def test_future_donation_date_is_rejected(self):
        profile = self.make_profile(days_ago=-1)  # tomorrow
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("last_donation_date", ctx.exception.message_dict)

    def test_invalid_phone_is_rejected(self):
        profile = self.make_profile(phone="12345")
        with self.assertRaises(ValidationError) as ctx:
            profile.full_clean()
        self.assertIn("phone", ctx.exception.message_dict)
