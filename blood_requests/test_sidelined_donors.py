"""A donor who is resting or switched off is not shown other people's requests."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.tests import make_donor, make_hospital, make_location, make_request

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class SidelinedDonors(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.family = User.objects.create_user(username="family", password="x")
        self.request_obj = make_request(
            self.family, self.location, hospital=self.hospital, blood_type="A+", patient_name="Someone Else's Patient"
        )
        self.user = User.objects.create_user(username="donor", password="x")
        self.donor = make_donor("Donor", "O+", self.location, user=self.user)
        self.client.force_login(self.user)
        self.detail = reverse("blood_requests:detail", args=[self.request_obj.pk])

    def rest(self):
        self.donor.last_donation_date = timezone.localdate() - timedelta(days=20)
        self.donor.save()

    def switch_off(self):
        self.donor.is_available = False
        self.donor.save()

    def test_a_ready_donor_sees_and_opens_requests_as_before(self):
        self.assertContains(self.client.get(reverse("donors:profile")), self.detail)
        self.assertEqual(self.client.get(self.detail).status_code, 200)
        self.assertEqual(self.client.get(reverse("blood_requests:list")).status_code, 200)

    def test_a_resting_donor_cannot_open_a_request_or_the_board(self):
        self.rest()
        for url in (self.detail, reverse("blood_requests:list")):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("donors:profile"), fetch_redirect_response=False)

    def test_an_unavailable_donor_cannot_open_a_request_or_the_board(self):
        self.switch_off()
        for url in (self.detail, reverse("blood_requests:list")):
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse("donors:profile"), fetch_redirect_response=False)

    def test_the_dashboard_says_why_instead_of_listing_requests(self):
        self.rest()
        for url in (reverse("donors:profile"), reverse("core:dashboard")):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn("You are in your resting period until", html)
                self.assertNotIn(self.detail, html)
        self.switch_off()
        html = self.client.get(reverse("donors:profile")).content.decode()
        self.assertIn("You are marked as unavailable", html)
        self.assertNotIn(self.detail, html)

    def test_the_message_is_shown_after_being_sent_back(self):
        self.rest()
        response = self.client.get(self.detail, follow=True)
        self.assertContains(response, "You are in your resting period until")

    def test_a_resting_donor_can_still_open_their_own_request(self):
        self.rest()
        own = make_request(self.user, self.location, hospital=self.hospital, patient_name="My Own Patient")
        self.assertEqual(self.client.get(reverse("blood_requests:detail", args=[own.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("blood_requests:mine")).status_code, 200)

    def test_people_who_are_not_donors_are_not_affected(self):
        plain = User.objects.create_user(username="plain", password="x")
        self.client.force_login(plain)
        self.assertEqual(self.client.get(self.detail).status_code, 200)
        self.assertEqual(self.client.get(reverse("blood_requests:list")).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(self.detail).status_code, 200)

    def test_a_resting_donor_cannot_offer_to_help_by_posting_directly(self):
        self.rest()
        response = self.client.post(reverse("blood_requests:respond", args=[self.request_obj.pk]))
        self.assertEqual(self.request_obj.responses.count(), 0)
        self.assertLess(response.status_code, 400)
