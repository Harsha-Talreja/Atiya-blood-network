"""One open offer at a time, taking an offer back, and the commitment ending by itself."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from core.constants import STATUS_FULFILLED, STATUS_REJECTED
from notifications.models import Notification

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class Commitment(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner_a = User.objects.create_user(username="owner_a", password="x")
        self.owner_b = User.objects.create_user(username="owner_b", password="x")
        self.first = make_request(self.owner_a, self.location, hospital=self.hospital, patient_name="First Patient")
        self.second = make_request(self.owner_b, self.location, hospital=self.hospital, patient_name="Second Patient")
        self.user = User.objects.create_user(username="donor", password="x")
        self.donor = make_donor("Donor", "O-", self.location, user=self.user)
        self.client.force_login(self.user)

    def respond(self, req):
        return self.client.post(reverse("blood_requests:respond", args=[req.pk]), follow=True)

    def withdraw(self, req):
        return self.client.post(reverse("blood_requests:withdraw", args=[req.pk]), follow=True)

    def offers(self):
        return DonorResponse.objects.filter(donor=self.donor).count()

    # ------------------------------------------------------------ the rule

    def test_a_second_offer_is_refused_while_the_first_request_is_open(self):
        self.respond(self.first)
        response = self.respond(self.second)
        self.assertEqual(self.offers(), 1)
        self.assertFalse(DonorResponse.objects.filter(request=self.second).exists())
        self.assertContains(response, "already offered to help First Patient")

    def test_the_detail_page_explains_why_and_links_to_the_first_request(self):
        self.respond(self.first)
        html = self.client.get(reverse("blood_requests:detail", args=[self.second.pk])).content.decode()
        self.assertNotIn(">I can help<", html)
        self.assertIn("already offered to help First Patient", html)
        self.assertIn(reverse("blood_requests:detail", args=[self.first.pk]), html)

    def test_offering_on_the_same_request_twice_still_says_duplicate(self):
        self.respond(self.first)
        response = self.respond(self.first)
        self.assertContains(response, "already offered to help with this request")

    # ------------------------------------------------------------ withdrawing

    def test_withdrawing_removes_the_offer_and_frees_the_donor(self):
        self.respond(self.first)
        self.withdraw(self.first)
        self.assertEqual(self.offers(), 0)
        self.respond(self.second)
        self.assertTrue(DonorResponse.objects.filter(request=self.second, donor=self.donor).exists())

    def test_the_requester_and_hospital_staff_are_told(self):
        self.respond(self.first)
        Notification.objects.all().delete()
        self.withdraw(self.first)
        note = Notification.objects.get(user=self.owner_a, kind=Notification.DONOR_RESPONSE)
        self.assertIn("withdrew", note.message)

    def test_the_withdraw_button_shows_on_an_open_request_you_offered_on(self):
        self.respond(self.first)
        html = self.client.get(reverse("blood_requests:detail", args=[self.first.pk])).content.decode()
        self.assertIn("Withdraw my offer", html)

    def test_you_cannot_withdraw_an_offer_you_never_made(self):
        self.withdraw(self.first)
        self.assertEqual(Notification.objects.filter(user=self.owner_a, kind=Notification.DONOR_RESPONSE).count(), 0)

    def test_someone_elses_offer_cannot_be_withdrawn(self):
        self.respond(self.first)
        other = User.objects.create_user(username="other", password="x")
        make_donor("Other", "O-", self.location, user=other)
        self.client.force_login(other)
        self.withdraw(self.first)
        self.assertEqual(self.offers(), 1)

    def test_an_offer_cannot_be_withdrawn_once_the_request_is_fulfilled(self):
        self.respond(self.first)
        BloodRequest.objects.filter(pk=self.first.pk).update(status=STATUS_FULFILLED)
        self.withdraw(self.first)
        self.assertEqual(self.offers(), 1)

    def test_withdrawing_needs_a_post(self):
        self.respond(self.first)
        response = self.client.get(reverse("blood_requests:withdraw", args=[self.first.pk]))
        self.assertEqual(response.status_code, 405)

    # --------------------------------------------------- ends by itself

    def test_the_commitment_ends_when_the_request_is_fulfilled(self):
        self.respond(self.first)
        BloodRequest.objects.filter(pk=self.first.pk).update(status=STATUS_FULFILLED)
        self.respond(self.second)
        self.assertTrue(DonorResponse.objects.filter(request=self.second).exists())

    def test_the_commitment_ends_when_the_request_expires(self):
        self.respond(self.first)
        BloodRequest.objects.filter(pk=self.first.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        self.respond(self.second)
        self.assertTrue(DonorResponse.objects.filter(request=self.second).exists())

    def test_the_commitment_ends_when_the_request_is_rejected(self):
        self.respond(self.first)
        BloodRequest.objects.filter(pk=self.first.pk).update(status=STATUS_REJECTED)
        self.respond(self.second)
        self.assertTrue(DonorResponse.objects.filter(request=self.second).exists())

    def test_a_different_donor_is_not_affected_by_this_donors_commitment(self):
        self.respond(self.first)
        other = User.objects.create_user(username="other", password="x")
        make_donor("Other", "O-", self.location, user=other)
        self.client.force_login(other)
        self.respond(self.second)
        self.assertTrue(DonorResponse.objects.filter(request=self.second).exists())


@FAST_HASHER
class SameCityOnly(TestCase):
    """A donor can offer only on requests in their own city."""

    def setUp(self):
        self.sukkur = make_location("Sukkur", "Military Road")
        self.khairpur = make_location("Khairpur", "Faiz Ganj")
        self.owner = User.objects.create_user(username="owner", password="x")
        self.far = make_request(
            self.owner, self.khairpur, hospital=make_hospital("Civil Hospital Khairpur", self.khairpur),
            patient_name="Khairpur Patient",
        )
        self.near = make_request(
            self.owner, self.sukkur, hospital=make_hospital("Civil Hospital", self.sukkur),
            patient_name="Sukkur Patient",
        )
        self.user = User.objects.create_user(username="donor", password="x")
        self.donor = make_donor("Donor", "O-", self.sukkur, user=self.user)
        self.client.force_login(self.user)

    def respond(self, req):
        return self.client.post(reverse("blood_requests:respond", args=[req.pk]), follow=True)

    def test_a_sukkur_donor_cannot_offer_on_a_khairpur_request(self):
        response = self.respond(self.far)
        self.assertFalse(DonorResponse.objects.filter(request=self.far).exists())
        self.assertContains(response, "This request is in Khairpur")
        self.assertContains(response, "your donor profile says Sukkur")

    def test_the_khairpur_page_has_no_i_can_help_button_for_a_sukkur_donor(self):
        html = self.client.get(reverse("blood_requests:detail", args=[self.far.pk])).content.decode()
        self.assertNotIn(">I can help<", html)
        self.assertIn("This request is in Khairpur", html)

    def test_a_sukkur_donor_can_offer_on_a_sukkur_request(self):
        self.respond(self.near)
        self.assertTrue(DonorResponse.objects.filter(request=self.near, donor=self.donor).exists())

    def test_a_different_area_in_the_same_city_is_still_allowed(self):
        other_area = make_location("Sukkur", "Old Sukkur")
        DonorProfileMove = type(self.donor)
        DonorProfileMove.objects.filter(pk=self.donor.pk).update(location=other_area)
        self.respond(self.near)
        self.assertTrue(DonorResponse.objects.filter(request=self.near).exists())

    def test_moving_city_in_the_profile_opens_the_new_citys_requests(self):
        type(self.donor).objects.filter(pk=self.donor.pk).update(location=self.khairpur)
        self.respond(self.far)
        self.assertTrue(DonorResponse.objects.filter(request=self.far).exists())
