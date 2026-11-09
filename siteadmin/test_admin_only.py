"""An admin account has the admin panel and nothing on the donor or requester side."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from blood_requests.models import BloodRequest
from core.models import Location
from donors.models import DonorProfile

User = get_user_model()

BLOCKED_GET = ["donors:profile", "donors:edit", "donors:search", "blood_requests:new", "blood_requests:mine"]


class AdminOnlyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("boss", password="pass-12345", is_staff=True)
        cls.person = User.objects.create_user("ordinary", password="pass-12345")

    def test_dashboard_sends_an_admin_to_the_panel(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("core:dashboard")), reverse("siteadmin:overview"))

    def test_an_ordinary_account_still_gets_its_dashboard(self):
        self.client.force_login(self.person)
        self.assertEqual(self.client.get(reverse("core:dashboard")).status_code, 200)

    def test_donor_and_requester_pages_redirect_an_admin(self):
        self.client.force_login(self.admin)
        for name in BLOCKED_GET:
            with self.subTest(name=name):
                self.assertRedirects(self.client.get(reverse(name)), reverse("siteadmin:overview"))

    def test_posting_a_request_or_registering_is_refused_for_an_admin(self):
        self.client.force_login(self.admin)
        before = BloodRequest.objects.count()
        self.client.post(reverse("blood_requests:new"), {"blood_type": "A+"})
        self.client.post(reverse("donors:edit"), {"full_name": "Boss"})
        self.assertEqual(BloodRequest.objects.count(), before)
        self.assertFalse(DonorProfile.objects.filter(user=self.admin).exists())

    def test_ordinary_account_can_still_open_those_pages(self):
        self.client.force_login(self.person)
        for name in ("donors:edit", "blood_requests:new", "blood_requests:mine"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_the_site_shows_an_admin_no_donate_or_request_buttons(self):
        self.client.force_login(self.admin)
        page = self.client.get(reverse("core:home")).content.decode()
        for text in ("Request blood", "I need blood", "Become a donor"):
            with self.subTest(text=text):
                self.assertNotIn(text, page)
        self.assertIn(reverse("siteadmin:overview"), page)

    def test_an_ordinary_visitor_still_sees_them(self):
        page = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("Request blood", page)
        self.assertIn("Become a donor", page)

    def test_the_admin_panel_itself_still_works(self):
        self.client.force_login(self.admin)
        for name in ("siteadmin:overview", "siteadmin:users"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
