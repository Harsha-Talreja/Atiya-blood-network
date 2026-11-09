from django.contrib.auth import get_user_model
from django.test import TestCase

from blood_requests.services import has_reached_daily_limit, requests_posted_today
from blood_requests.tests import make_hospital, make_location, make_request
from core.constants import MAX_REQUESTS_PER_USER_PER_DAY

User = get_user_model()


class DailyLimitTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.user = User.objects.create_user(username="requester")

    def test_zero_requests_today_by_default(self):
        self.assertEqual(requests_posted_today(self.user), 0)
        self.assertFalse(has_reached_daily_limit(self.user))

    def test_counts_only_this_users_requests(self):
        other = User.objects.create_user(username="someone_else")
        make_request(other, self.location, hospital=self.hospital)
        self.assertEqual(requests_posted_today(self.user), 0)

    def test_reaches_the_limit_at_exactly_max_requests(self):
        for _ in range(MAX_REQUESTS_PER_USER_PER_DAY - 1):
            make_request(self.user, self.location, hospital=self.hospital)
        self.assertFalse(has_reached_daily_limit(self.user))

        make_request(self.user, self.location, hospital=self.hospital)
        self.assertEqual(requests_posted_today(self.user), MAX_REQUESTS_PER_USER_PER_DAY)
        self.assertTrue(has_reached_daily_limit(self.user))
