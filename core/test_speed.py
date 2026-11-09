"""Speed changes: they must make the site lighter without changing what people see."""
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.core.cache import caches
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from blood_requests import services
from blood_requests.models import DonorResponse
from blood_requests.tests import make_donor, make_location, make_request

User = get_user_model()
LOCMEM = override_settings(CACHES={
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "speed-tests"},
    "snap": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "speed-tests-snap"},
})
ROOT = Path(settings.BASE_DIR)


class PasswordHashTests(SimpleTestCase):
    def test_new_passwords_use_the_lighter_setting(self):
        encoded = make_password("a-strong-pass-123")
        self.assertTrue(encoded.startswith("pbkdf2_sha256$600000$"))
        self.assertTrue(check_password("a-strong-pass-123", encoded))
        self.assertFalse(check_password("wrong", encoded))

    def test_old_heavier_passwords_still_work_and_are_upgraded(self):
        from django.contrib.auth.hashers import PBKDF2PasswordHasher

        class Old(PBKDF2PasswordHasher):
            iterations = 1_500_000

        old = Old().encode("old-pass-12345", "somesalt")
        self.assertTrue(old.startswith("pbkdf2_sha256$1500000$"))
        upgraded = []
        self.assertTrue(check_password("old-pass-12345", old, setter=upgraded.append))
        self.assertEqual(upgraded, ["old-pass-12345"])  # Django re-saves it with the new setting
        self.assertEqual(identify_hasher(old).algorithm, "pbkdf2_sha256")


@LOCMEM
class EscalationThrottleTests(TestCase):
    def setUp(self):
        caches["snap"].clear()

    def test_the_deadline_check_runs_once_per_window_not_on_every_poll(self):
        with mock.patch.object(services, "escalate_overdue_requests", return_value=3) as check:
            self.assertEqual(services.escalate_overdue_requests_soon(), 3)
            self.assertEqual(services.escalate_overdue_requests_soon(), 0)
            self.assertEqual(services.escalate_overdue_requests_soon(), 0)
        self.assertEqual(check.call_count, 1)

    def test_polling_the_bell_does_not_open_a_write_every_time(self):
        user = User.objects.create_user(username="poller", password="x")
        self.client.force_login(user)
        with mock.patch.object(services, "escalate_overdue_requests", return_value=0) as check:
            for _ in range(5):
                self.assertEqual(self.client.get(reverse("notifications:count")).status_code, 200)
        self.assertEqual(check.call_count, 1)


class TestsSeeFreshDataTests(SimpleTestCase):
    def test_the_cache_does_nothing_while_tests_run(self):
        self.assertIn("dummy", settings.CACHES["snap"]["BACKEND"])
        self.assertIn("locmem", settings.CACHES["default"]["BACKEND"])  # the sign-in lock still works


@LOCMEM
class CountedNumbersTests(TestCase):
    def setUp(self):
        caches["snap"].clear()

    def test_the_navbar_count_is_remembered_between_pages(self):
        with mock.patch("blood_requests.selectors.open_requests") as fake:
            fake.return_value.count.return_value = 7
            from core.templatetags.core_extras import live_request_count
            self.assertEqual(live_request_count(), 7)
            fake.return_value.count.return_value = 99
            self.assertEqual(live_request_count(), 7)  # still the remembered number
        self.assertEqual(fake.call_count, 1)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LiveOffersTests(TestCase):
    def test_the_offers_box_is_marked_so_it_can_refresh_in_place(self):
        location = make_location("Sukkur", "Military Road")
        owner = User.objects.create_user(username="owner", password="x")
        req = make_request(owner, location, blood_type="A+")
        DonorResponse.objects.create(request=req, donor=make_donor("Ali Raza", "O+", location))
        self.client.force_login(owner)
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertEqual(html.count('data-live-key="offers"'), 1)
        self.assertIn("Ali Raza", html)

    def test_a_stranger_gets_no_live_offers_box(self):
        location = make_location("Sukkur", "Military Road")
        owner = User.objects.create_user(username="owner", password="x")
        req = make_request(owner, location, blood_type="A+")
        stranger = User.objects.create_user(username="stranger", password="x")
        self.client.force_login(stranger)
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertNotIn("data-live-key", html)


class FrontEndSpeedTests(SimpleTestCase):
    def test_polling_is_every_30_seconds_and_stops_when_idle(self):
        js = (ROOT / "static/js/notifications.js").read_text()
        self.assertIn("var every = 30000;", js)
        self.assertIn("idleAfter", js)
        self.assertIn("document.hidden", js)
        self.assertIn("data-live-key", js)

    def test_reveal_animations_are_short(self):
        js = (ROOT / "static/js/main.js").read_text()
        self.assertIn("AOS.init({ duration: 450,", js)
