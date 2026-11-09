"""Logins end with the browser. Only a ticked "Remember me" (donors and requesters)
lasts longer, and admin and hospital accounts are strict whatever they tick."""
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.tests import make_hospital, make_location
from hospitals.models import HospitalAccount

User = get_user_model()
PASSWORD = "Str0ng-pass-123"
FAST = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def log_in(client, username, remember=False):
    data = {"username": username, "password": PASSWORD}
    if remember:
        data["remember"] = "on"
    return client.post(reverse("accounts:login"), data)


def is_browser_session_cookie(response):
    cookie = response.cookies[settings.SESSION_COOKIE_NAME]
    return cookie["max-age"] == "" and cookie["expires"] == ""


@FAST
class SessionLengthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username="plain", password=PASSWORD)
        User.objects.create_user(username="boss", password=PASSWORD, is_staff=True)
        hospital = make_hospital("Civil Hospital", make_location("Sukkur", "Military Road"))
        desk = User.objects.create_user(username="desk", password=PASSWORD)
        HospitalAccount.objects.create(user=desk, hospital=hospital, staff_name="Dr. Desk")

    def test_settings(self):
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 60 * 60 * 12)
        self.assertEqual(settings.REMEMBER_ME_AGE, 60 * 60 * 24 * 14)
        self.assertEqual(settings.STRICT_IDLE_SECONDS, 30 * 60)

    def test_login_page_offers_remember_me(self):
        html = self.client.get(reverse("accounts:login")).content.decode()
        self.assertIn('name="remember"', html)
        self.assertIn("Remember me on this device", html)

    def test_plain_login_ends_with_the_browser(self):
        resp = log_in(self.client, "plain")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(is_browser_session_cookie(resp))

    def test_remember_me_keeps_a_donor_logged_in_for_two_weeks(self):
        resp = log_in(self.client, "plain", remember=True)
        cookie = resp.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(int(cookie["max-age"]), settings.REMEMBER_ME_AGE)
        self.assertFalse(self.client.session.get("strict"))

    def test_remember_me_is_ignored_for_admin(self):
        resp = log_in(self.client, "boss", remember=True)
        self.assertTrue(is_browser_session_cookie(resp))
        self.assertTrue(self.client.session.get("strict"))

    def test_remember_me_is_ignored_for_hospital_accounts(self):
        resp = log_in(self.client, "desk", remember=True)
        self.assertTrue(is_browser_session_cookie(resp))
        self.assertTrue(self.client.session.get("strict"))


@FAST
class IdleLogoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username="plain", password=PASSWORD)
        User.objects.create_user(username="boss", password=PASSWORD, is_staff=True)
        hospital = make_hospital("Civil Hospital", make_location("Sukkur", "Military Road"))
        desk = User.objects.create_user(username="desk", password=PASSWORD)
        HospitalAccount.objects.create(user=desk, hospital=hospital, staff_name="Dr. Desk")

    def _age_session(self, seconds):
        session = self.client.session
        session["last_seen"] = int(time.time()) - seconds
        session.save()

    def test_admin_is_logged_out_after_30_idle_minutes(self):
        log_in(self.client, "boss")
        self.client.get(reverse("siteadmin:overview"))
        self._age_session(31 * 60)
        resp = self.client.get(reverse("siteadmin:overview"))
        self.assertRedirects(resp, reverse("accounts:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_hospital_is_logged_out_after_30_idle_minutes(self):
        log_in(self.client, "desk")
        self.client.get(reverse("hospitals:dashboard"))
        self._age_session(31 * 60)
        resp = self.client.get(reverse("hospitals:dashboard"))
        self.assertRedirects(resp, reverse("accounts:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_active_hospital_account_stays_logged_in(self):
        log_in(self.client, "desk")
        self.client.get(reverse("hospitals:dashboard"))
        self._age_session(10 * 60)
        resp = self.client.get(reverse("hospitals:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

    def test_donor_is_never_logged_out_for_being_idle(self):
        log_in(self.client, "plain", remember=True)
        self._age_session(5 * 60 * 60)  # no effect: only strict accounts are checked
        resp = self.client.get(reverse("core:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)
