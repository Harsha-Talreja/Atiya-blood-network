"""The overview's number row and seven-day chart.

The figures come from the same selectors the rest of the panel uses, so these
tests only check that they reach the page and that the chart covers a full week
even when nothing was posted.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.tests import make_hospital, make_location, make_request

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class OverviewNumbersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user("panel_staff", password="pw-12345-x", is_staff=True)

    def setUp(self):
        self.client.force_login(self.staff)

    def test_empty_database_still_draws_seven_days(self):
        response = self.client.get(reverse("siteadmin:overview"))
        self.assertEqual(response.status_code, 200)
        trend = response.context["trend"]
        self.assertEqual(len(trend["days"]), 7)
        self.assertEqual(trend["total"], 0)

    def test_number_row_shows_the_four_counts(self):
        response = self.client.get(reverse("siteadmin:overview"))
        for label in ("Open requests", "Unchecked", "Donors ready", "Open reports"):
            self.assertContains(response, label)

    def test_chart_counts_a_request_posted_today(self):
        location = make_location("Sukkur", "Barrage Road")
        hospital = make_hospital("Test Hospital", location)
        requester = User.objects.create_user("poster", password="pw-12345-x")
        make_request(requester, location, hospital=hospital)
        response = self.client.get(reverse("siteadmin:overview"))
        self.assertEqual(response.context["trend"]["total"], 1)
        self.assertEqual(response.context["trend"]["days"][-1]["count"], 1)
