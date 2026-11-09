"""A donor who offered to help can tell the requester and the hospital they have reached the hospital."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import DonorResponse
from blood_requests.services import fulfil_request
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from hospitals.test_views import make_hospital_account
from notifications.models import Notification

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ReachedTheHospital(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.desk = make_hospital_account("civil_desk", self.hospital)
        self.family = User.objects.create_user(username="family", password="x")
        self.req = make_request(self.family, self.location, hospital=self.hospital, blood_type="A+")
        self.donor = make_donor("Helper", "O+", self.location)
        self.offer = DonorResponse.objects.create(request=self.req, donor=self.donor)
        self.url = reverse("blood_requests:arrived", args=[self.req.pk])
        self.detail = reverse("blood_requests:detail", args=[self.req.pk])

    def test_the_donor_can_say_they_have_arrived(self):
        self.client.force_login(self.donor.user)
        response = self.client.post(self.url)
        self.assertRedirects(response, self.detail, fetch_redirect_response=False)
        self.offer.refresh_from_db()
        self.assertIsNotNone(self.offer.arrived_at)

    def test_the_requester_and_the_hospital_are_told(self):
        self.client.force_login(self.donor.user)
        self.client.post(self.url)
        mine = Notification.objects.filter(user=self.family, message__contains="has reached")
        self.assertEqual(mine.count(), 1)
        self.assertIn("Civil Hospital", mine.get().message)
        theirs = Notification.objects.filter(user=self.desk.user, message__contains="has reached your hospital")
        self.assertEqual(theirs.count(), 1)

    def test_pressing_twice_does_not_tell_everyone_twice(self):
        self.client.force_login(self.donor.user)
        self.client.post(self.url)
        first = DonorResponse.objects.get(pk=self.offer.pk).arrived_at
        self.client.post(self.url)
        self.assertEqual(Notification.objects.filter(user=self.family, message__contains="has reached").count(), 1)
        self.assertEqual(DonorResponse.objects.get(pk=self.offer.pk).arrived_at, first)

    def test_a_plain_link_cannot_do_it(self):
        self.client.force_login(self.donor.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_someone_who_did_not_offer_cannot(self):
        stranger = make_donor("Stranger", "O+", self.location)
        self.client.force_login(stranger.user)
        response = self.client.post(self.url, follow=True)
        self.assertContains(response, "haven&#x27;t offered")
        self.assertFalse(Notification.objects.filter(message__contains="has reached").exists())

    def test_the_requester_cannot_do_it_for_the_donor(self):
        self.client.force_login(self.family)
        self.client.post(self.url)
        self.offer.refresh_from_db()
        self.assertIsNone(self.offer.arrived_at)

    def test_it_cannot_be_done_on_a_closed_request(self):
        fulfil_request(self.req.pk)
        self.client.force_login(self.donor.user)
        self.client.post(self.url)
        self.offer.refresh_from_db()
        self.assertIsNone(self.offer.arrived_at)

    def test_hospitals_and_admins_cannot_use_it(self):
        self.client.force_login(self.desk.user)
        self.assertRedirects(self.client.post(self.url), reverse("hospitals:dashboard"), fetch_redirect_response=False)
        staff = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.offer.refresh_from_db()
        self.assertIsNone(self.offer.arrived_at)

    def test_the_donor_sees_the_button_then_a_confirmation_line(self):
        self.client.force_login(self.donor.user)
        html = self.client.get(self.detail).content.decode()
        self.assertIn("I&#x27;ve reached the hospital", html)
        self.assertIn(self.url, html)
        self.client.post(self.url)
        html = self.client.get(self.detail).content.decode()
        self.assertNotIn(">I&#x27;ve reached the hospital<", html)
        self.assertIn("You told the requester you are at the hospital", html)

    def test_the_requester_sees_a_badge_only_after_the_donor_arrives(self):
        self.client.force_login(self.family)
        html = self.client.get(self.detail).content.decode()
        self.assertNotIn("arr-chip", html)
        self.assertIn("A donor reaches the hospital", html)
        DonorResponse.objects.filter(pk=self.offer.pk).update(arrived_at=timezone.now())
        html = self.client.get(self.detail).content.decode()
        self.assertIn("arr-chip", html)
        self.assertIn("At the hospital", html)
        self.assertIn("A donor reached the hospital", html)

    def test_other_people_never_see_who_arrived(self):
        DonorResponse.objects.filter(pk=self.offer.pk).update(arrived_at=timezone.now())
        other = User.objects.create_user(username="other", password="x")
        self.client.force_login(other)
        html = self.client.get(self.detail).content.decode()
        self.assertNotIn("arr-chip", html)
        self.assertNotIn("Helper", html)

    def test_withdrawing_removes_the_offer_and_the_badge(self):
        DonorResponse.objects.filter(pk=self.offer.pk).update(arrived_at=timezone.now())
        self.client.force_login(self.donor.user)
        self.client.post(reverse("blood_requests:withdraw", args=[self.req.pk]))
        self.client.force_login(self.family)
        self.assertNotIn("arr-chip", self.client.get(self.detail).content.decode())

    def test_the_button_works_in_urdu_and_sindhi(self):
        self.client.force_login(self.donor.user)
        for code, word in (("ur", "ہسپتال پہنچ گیا ہوں"), ("sd", "اسپتال پهچي ويس")):
            self.client.cookies["django_language"] = code
            self.assertContains(self.client.get(self.detail), word)
