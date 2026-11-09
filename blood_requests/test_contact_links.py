"""The Call and WhatsApp buttons next to donors who offered to help.

The buttons are a shortcut for the person who posted the request, so they must
(a) only exist for donors who agreed to share their number, (b) only be shown to
the people allowed to see who offered, and (c) open a message with the right
details. The layout around them is checked too: a closed request lists only the
donors who helped, and "Donors ready nearby" goes away.
"""
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.contact import international_digits, tel_url, whatsapp_url
from blood_requests.models import DonorResponse
from core.constants import STATUS_FULFILLED
from blood_requests.tests import make_donor, make_hospital, make_location, make_request

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


class NumberFormattingTests(SimpleTestCase):
    def test_local_and_international_forms_give_the_same_digits(self):
        self.assertEqual(international_digits("03001234567"), "923001234567")
        self.assertEqual(international_digits("+923001234567"), "923001234567")
        self.assertEqual(international_digits("923001234567"), "923001234567")
        self.assertEqual(international_digits("0300 123-4567"), "923001234567")

    def test_anything_else_gives_nothing_so_no_broken_link_is_made(self):
        for bad in ("", None, "12345", "0212345678", "+15551234567", "abc"):
            self.assertEqual(international_digits(bad), "")
            self.assertEqual(tel_url(bad), "")
            self.assertEqual(whatsapp_url(bad, "hi"), "")

    def test_the_whatsapp_text_is_url_encoded(self):
        url = whatsapp_url("03001234567", "A+ & B: ok?")
        self.assertTrue(url.startswith("https://wa.me/923001234567?text="))
        self.assertEqual(parse_qs(urlparse(url).query)["text"], ["A+ & B: ok?"])


@FAST_HASHER
class ButtonTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x", first_name="Hamza")
        self.req = make_request(
            self.owner, self.location, hospital=self.hospital, blood_type="A+",
            contact_phone="03007776655", patient_name="Pranjal", units_needed=2,
        )
        self.url = reverse("blood_requests:detail", args=[self.req.pk])
        self.sharing = make_donor("Ali Raza", "O+", self.location)
        self.sharing.phone_consent = True
        self.sharing.save(update_fields=["phone_consent"])
        self.private = make_donor("Sana Memon", "A+", self.location)
        for donor in (self.sharing, self.private):
            DonorResponse.objects.create(request=self.req, donor=donor)

    def page(self, user):
        self.client.force_login(user)
        return self.client.get(self.url)

    def test_a_donor_who_shares_their_number_gets_both_buttons(self):
        html = self.page(self.owner).content.decode()
        self.assertIn('href="tel:+923001234567"', html)
        self.assertIn('href="https://wa.me/923001234567?text=', html)
        self.assertIn('aria-label="Call Ali Raza"', html)
        self.assertIn("Message Ali Raza on WhatsApp", html)

    def test_a_donor_who_hides_their_number_gets_no_buttons(self):
        response = self.page(self.owner)
        offers = {o["donor"].full_name: o for o in response.context["offers"]}
        self.assertEqual(offers["Sana Memon"]["tel"], "")
        self.assertEqual(offers["Sana Memon"]["wa"], "")
        self.assertContains(response, "Number not shared")
        self.assertNotContains(response, "Call Sana Memon")

    def test_the_message_carries_the_requesters_details(self):
        response = self.page(self.owner)
        link = {o["donor"].full_name: o for o in response.context["offers"]}["Ali Raza"]["wa"]
        text = parse_qs(urlparse(link).query)["text"][0]
        for part in ("Ali", "Hamza", "A+ blood (2 units)", "Pranjal", "Civil Hospital", "Sukkur", "03007776655"):
            self.assertIn(part, text)

    def test_once_fulfilled_the_message_becomes_a_thank_you(self):
        self.req.status = STATUS_FULFILLED
        self.req.fulfilled_at = timezone.now()
        self.req.save(update_fields=["status", "fulfilled_at"])
        response = self.page(self.owner)
        link = {o["donor"].full_name: o for o in response.context["offers"]}["Ali Raza"]["wa"]
        text = parse_qs(urlparse(link).query)["text"][0]
        self.assertIn("thank you", text.lower())
        self.assertNotIn("is needed", text)
        self.assertContains(response, "Thank Ali Raza on WhatsApp")

    def test_a_stranger_gets_no_links_and_no_list(self):
        stranger = User.objects.create_user(username="stranger", password="x")
        response = self.page(stranger)
        self.assertNotIn("offers", response.context)
        self.assertNotContains(response, "wa.me")
        self.assertNotContains(response, "tel:+92")

    def test_an_admin_sees_the_buttons_too(self):
        boss = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.assertContains(self.page(boss), "wa.me/923001234567")


@FAST_HASHER
class ClosedRequestLayoutTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location, blood_type="A+")
        make_donor("Nearby Donor", "A+", self.location)
        self.url = reverse("blood_requests:detail", args=[self.req.pk])
        self.client.force_login(self.owner)

    def close(self):
        self.req.status = STATUS_FULFILLED
        self.req.fulfilled_at = timezone.now()
        self.req.save(update_fields=["status", "fulfilled_at"])

    def test_an_open_request_lists_donors_who_offered_and_donors_ready_nearby(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Donors who offered", html)
        self.assertIn("Donors ready nearby", html)
        self.assertIn("Nearby Donor", html)

    def test_a_fulfilled_request_lists_only_the_donors_who_helped(self):
        self.close()
        response = self.client.get(self.url)
        html = response.content.decode()
        self.assertIn("Donors who helped", html)
        self.assertNotIn("Donors who offered", html)
        self.assertNotIn("Donors ready nearby", html)
        self.assertNotIn("Nearby Donor", html)
        self.assertNotIn("matching_donors", response.context)

    def test_the_progress_is_one_thin_line_not_the_old_tracking_card(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('class="tl tl-line"', html)
        self.assertNotIn("track-card", html)


@FAST_HASHER
class MyRequestsLayoutTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.me = User.objects.create_user(username="requester", password="x")
        self.client.force_login(self.me)
        self.open = make_request(self.me, self.location)
        self.done = make_request(self.me, self.location)
        self.done.status = STATUS_FULFILLED
        self.done.fulfilled_at = timezone.now()
        self.done.save(update_fields=["status", "fulfilled_at"])

    def test_a_fulfilled_request_leaves_the_open_list_for_past_requests(self):
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertEqual([row["req"].pk for row in response.context["open_rows"]], [self.open.pk])
        self.assertEqual([row["req"].pk for row in response.context["past_rows"]], [self.done.pk])
        html = response.content.decode()
        self.assertIn("Past requests", html)
        # Only the open request is a big row with a progress line and a fulfil button.
        self.assertEqual(html.count('class="tl tl-mini"'), 1)

    def test_no_past_section_when_nothing_is_closed(self):
        self.done.delete()
        self.assertNotContains(self.client.get(reverse("blood_requests:mine")), "Past requests")

    def test_when_everything_is_closed_the_page_says_so(self):
        self.open.delete()
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertContains(response, "No open requests")
        self.assertContains(response, "Past requests")
