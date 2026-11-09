"""The request form: one two-column card, blood type and urgency as buttons, no hint lines."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.models import BloodRequest
from blood_requests.test_views import request_form_data
from blood_requests.tests import make_hospital, make_location

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class RequestFormLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sana", "s@example.com", "x")
        self.client.force_login(self.user)
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.url = reverse("blood_requests:new")

    def page(self):
        return self.client.get(self.url).content.decode()

    def test_it_is_one_two_column_card_not_three_steps(self):
        html = self.page()
        self.assertIn('class="form-card form-card-wide mx-auto dform"', html)
        self.assertEqual(html.count('class="dform-cols"'), 1)
        self.assertIn("Who needs blood", html)
        self.assertIn("Where and contact", html)
        self.assertNotIn("data-wizard", html)

    def test_the_page_is_just_the_form_without_the_dashboard_panel(self):
        html = self.page()
        for gone in ('class="dside"', 'class="dtabs"', 'class="dpage-title"', 'class="vrail"'):
            with self.subTest(part=gone):
                self.assertNotIn(gone, html)

    def test_blood_type_is_eight_buttons(self):
        html = self.page()
        self.assertEqual(html.count('name="blood_type"'), 8)
        self.assertNotIn('<select name="blood_type"', html)

    def test_urgency_is_three_buttons_and_normal_is_chosen(self):
        html = self.page()
        self.assertEqual(html.count('name="urgency"'), 3)
        self.assertRegex(html, r'value="Normal"[^>]*checked')

    def test_the_old_hint_lines_are_gone(self):
        html = self.page()
        for gone in ("One unit is roughly one donation", "Critical stays open 24 hours",
                     "Only shown to signed-in users", "Up to 3 units go out normally",
                     "The request won&#x27;t be visible", "Anything else donors should know"):
            with self.subTest(text=gone):
                self.assertNotIn(gone, html)

    def test_the_hospital_line_is_kept_once_at_the_bottom(self):
        self.assertEqual(self.page().count("Donors can see the request after the hospital verifies it."), 1)

    def test_the_requests_left_count_is_in_the_card_head(self):
        html = self.page()
        start = html.index('class="form-card-head"')
        head = html[start:html.index("<form", start)]
        self.assertIn("3 of 3 requests remaining today", head)

    def test_the_extra_reason_box_is_still_in_the_form(self):
        html = self.page()
        self.assertIn('name="extra_reason"', html)
        self.assertIn("Why is extra blood needed?", html)
        self.assertIn("data-extra-reason", html)

    def test_a_request_posted_with_the_buttons_still_works(self):
        response = self.client.post(self.url, request_form_data(self.hospital, blood_type="A+", urgency="Urgent"))
        self.assertEqual(response.status_code, 302)
        request = BloodRequest.objects.get()
        self.assertEqual((request.blood_type, request.urgency), ("A+", "Urgent"))

    def test_leaving_the_blood_type_empty_asks_for_it(self):
        data = request_form_data(self.hospital)
        data.pop("blood_type")
        response = self.client.post(self.url, data)
        self.assertContains(response, "Choose the blood type needed.")
        self.assertFalse(BloodRequest.objects.exists())

    def test_a_form_that_failed_keeps_the_chosen_buttons(self):
        response = self.client.post(self.url, request_form_data(self.hospital, blood_type="B+", urgency="Critical", contact_phone="123"))
        html = response.content.decode()
        self.assertRegex(html, r'value="B\+"[^>]*checked')
        self.assertRegex(html, r'value="Critical"[^>]*checked')
