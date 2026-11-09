from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts import throttle

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="Ali", password="right-pass-1")
        self.url = reverse("accounts:login")

    def attempt(self, username="Ali", password="wrong", **extra):
        return self.client.post(self.url, {"username": username, "password": password}, **extra)

    def logged_in(self):
        return "_auth_user_id" in self.client.session

    def test_a_few_wrong_passwords_are_just_wrong(self):
        for _ in range(throttle.MAX_PER_USERNAME - 1):
            self.assertContains(self.attempt(), "don&#x27;t match")
        self.attempt(password="right-pass-1")
        self.assertTrue(self.logged_in())

    def test_after_the_limit_even_the_right_password_is_refused(self):
        for _ in range(throttle.MAX_PER_USERNAME):
            self.attempt()
        response = self.attempt(password="right-pass-1")
        self.assertContains(response, "Too many wrong attempts")
        self.assertFalse(self.logged_in())

    def test_the_lock_does_not_say_whether_the_username_exists(self):
        for _ in range(throttle.MAX_PER_USERNAME):
            self.attempt(username="nobody-here")
        self.assertContains(self.attempt(username="nobody-here"), "Too many wrong attempts")

    def test_another_username_is_not_locked_by_one_guesser(self):
        User.objects.create_user(username="sara", password="sara-pass-1")
        for _ in range(throttle.MAX_PER_USERNAME):
            self.attempt()
        self.attempt(username="sara", password="sara-pass-1")
        self.assertTrue(self.logged_in())

    def test_the_username_is_matched_ignoring_case_and_spaces_so_it_cannot_be_dodged(self):
        for name in ["Ali", "ali", "ALI", " ali", "aLi"]:
            self.attempt(username=name)
        self.assertTrue(throttle.is_locked(None, "ali"))

    def test_a_good_login_clears_the_count(self):
        for _ in range(throttle.MAX_PER_USERNAME - 1):
            self.attempt()
        self.attempt(password="right-pass-1")
        self.client.logout()
        for _ in range(throttle.MAX_PER_USERNAME - 1):
            self.attempt()
        self.attempt(password="right-pass-1")
        self.assertTrue(self.logged_in())

    def test_the_lock_ends_when_its_window_ends(self):
        for _ in range(throttle.MAX_PER_USERNAME):
            self.attempt()
        cache.clear()  # what the cache does when the window runs out
        self.attempt(password="right-pass-1")
        self.assertTrue(self.logged_in())

    def test_one_address_trying_many_usernames_is_stopped_too(self):
        for i in range(throttle.MAX_PER_IP):
            self.attempt(username=f"guess{i}")
        response = self.attempt(password="right-pass-1")
        self.assertContains(response, "Too many wrong attempts")

    def test_a_forged_forwarded_header_does_not_dodge_the_address_limit(self):
        for i in range(throttle.MAX_PER_IP):
            self.attempt(username=f"guess{i}", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}")
        self.assertContains(self.attempt(HTTP_X_FORWARDED_FOR="10.9.9.9"), "Too many wrong attempts")

    def test_blocked_accounts_still_get_the_blocked_message_not_the_lock(self):
        from accounts.models import UserBlock

        UserBlock.objects.create(user=self.user)
        self.assertContains(self.attempt(password="right-pass-1"), "blocked by an admin")
