"""The lock on the panel.

These tests walk siteadmin.urls itself rather than listing routes by hand, so a
view added later is covered the moment its URL is registered. If someone adds a
page and forgets @staff_only, test_every_page_refuses_a_signed_in_non_staff_user
fails and names the URL.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.models import Report
from blood_requests.tests import make_hospital, make_location, make_request
from siteadmin import urls as siteadmin_urls

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])

# Routes that change something are POST-only, so a GET to them is 405 rather than
# 200 even for staff. They are split out because the expected success code differs,
# not because they are checked any less.
ACTION_NAMES = {
    "request_verify", "request_timeout", "request_check", "request_remove",
    "report_resolve", "user_block", "user_unblock", "user_delete",
}


# Pages that take a pk but are read first and posted second, so a GET is a
# normal 200 for staff rather than a 405.
PAGES_WITH_PK = {"request_review"}


def all_routes():
    """(name, needs_pk) for every route in the admin panel's URL conf."""
    for pattern in siteadmin_urls.urlpatterns:
        name = pattern.name
        yield name, "<int:pk>" in str(pattern.pattern)


@FAST_HASHER
class PanelAccessTests(TestCase):
    """Three kinds of visitor, one expectation each, for every single route."""

    @classmethod
    def setUpTestData(cls):
        cls.location = make_location("Sukkur", "Military Road")
        cls.hospital = make_hospital("Civil Hospital", cls.location)
        cls.staff = User.objects.create_user("boss", password="pw", is_staff=True)
        cls.ordinary = User.objects.create_user("nobody", password="pw")
        cls.poster = User.objects.create_user("poster", password="pw")
        cls.request_obj = make_request(cls.poster, cls.location, hospital=cls.hospital)
        cls.report = Report.objects.create(
            request=cls.request_obj, reporter=cls.ordinary, reason="Fake or hoax"
        )

    def url_for(self, name, needs_pk):
        if not needs_pk:
            return reverse(f"siteadmin:{name}")
        pk = self.ordinary.pk if "user_" in name else (
            self.report.pk if name == "report_resolve" else self.request_obj.pk
        )
        return reverse(f"siteadmin:{name}", args=[pk])

    def test_every_route_sends_an_anonymous_visitor_to_the_login_page(self):
        for name, needs_pk in all_routes():
            with self.subTest(route=name):
                url = self.url_for(name, needs_pk)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302, f"{name} did not redirect")
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_every_page_refuses_a_signed_in_non_staff_user(self):
        """403, not a redirect: a redirect would tell an ordinary user there is
        something here worth trying again for."""
        self.client.force_login(self.ordinary)
        for name, needs_pk in all_routes():
            with self.subTest(route=name):
                url = self.url_for(name, needs_pk)
                get = self.client.get(url)
                self.assertEqual(get.status_code, 403, f"GET {name} was not refused")
                post = self.client.post(url, {})
                self.assertEqual(post.status_code, 403, f"POST {name} was not refused")

    def test_a_non_staff_user_cannot_block_anyone_even_by_posting_directly(self):
        """The one that matters most: the panel adds a way to block people, and an
        ordinary account must not be able to reach it by guessing the URL."""
        from accounts.models import UserBlock

        self.client.force_login(self.ordinary)
        response = self.client.post(reverse("siteadmin:user_block", args=[self.poster.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserBlock.objects.exists())

    def test_a_non_staff_user_cannot_delete_anyone_even_by_posting_directly(self):
        self.client.force_login(self.ordinary)
        before = User.objects.count()
        response = self.client.post(reverse("siteadmin:user_delete", args=[self.poster.pk]),
                                    {"confirm_username": self.poster.username})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.objects.count(), before)

    def test_every_page_opens_for_staff(self):
        self.client.force_login(self.staff)
        for name, needs_pk in all_routes():
            if name in ACTION_NAMES:
                continue
            with self.subTest(page=name):
                response = self.client.get(self.url_for(name, needs_pk))
                self.assertEqual(response.status_code, 200, f"{name} did not render")

    def test_an_action_cannot_be_triggered_by_a_get(self):
        """So a link, an image tag or a prefetch cannot change anything."""
        self.client.force_login(self.staff)
        for name, needs_pk in all_routes():
            if name not in ACTION_NAMES:
                continue
            with self.subTest(action=name):
                response = self.client.get(self.url_for(name, needs_pk))
                self.assertEqual(response.status_code, 405, f"GET {name} was allowed")

    def test_every_action_route_is_covered_by_this_test_file(self):
        """Guards the guard: if a POST route is added and not listed in
        ACTION_NAMES, the success-code tests above would silently skip it."""
        post_like = {
            name for name, needs_pk in all_routes()
            if needs_pk or name in ACTION_NAMES
        }
        unaccounted = post_like - ACTION_NAMES - PAGES_WITH_PK
        self.assertEqual(
            unaccounted, set(),
            "These routes take a pk but are not listed in ACTION_NAMES: "
            f"{sorted(unaccounted)}. Add them, or give them their own test.",
        )


@FAST_HASHER
class PanelIsNotAdvertisedTests(TestCase):
    def test_the_navbar_only_offers_the_panel_to_staff(self):
        ordinary = User.objects.create_user("plain", password="pw")
        self.client.force_login(ordinary)
        home = self.client.get(reverse("core:home"))
        self.assertNotContains(home, reverse("siteadmin:overview"))

    def test_staff_dashboard_address_leads_to_the_panel(self):
        staff = User.objects.create_user("boss2", password="pw", is_staff=True)
        self.client.force_login(staff)
        dashboard = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(dashboard, reverse("siteadmin:overview"))
