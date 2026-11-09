"""A new request is the hospital's to decide. Admins only see it once the hospital's wait runs out."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.selectors import awaiting_timeout_review, still_with_hospital
from blood_requests.tests import make_hospital, make_location, make_request

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class HospitalFirst(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.client.force_login(self.staff)
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner")

    def page(self, state="all"):
        return self.client.get(reverse("siteadmin:requests"), {"state": state}).content.decode()

    def test_a_fresh_request_is_not_in_the_admin_list(self):
        make_request(self.owner, self.location, hospital=self.hospital, is_verified=False, patient_name="Fresh Patient")
        for state in ("all", "unchecked", "live", "timeout"):
            with self.subTest(state=state):
                self.assertNotIn("Fresh Patient", self.page(state))

    def test_it_appears_for_the_admin_once_the_hospital_wait_is_over(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False, patient_name="Late Patient")
        BloodRequest.objects.filter(pk=req.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.assertIn("Late Patient", self.page("all"))
        self.assertIn("Late Patient", self.page("timeout"))

    def test_a_request_is_always_in_exactly_one_of_the_two_sets(self):
        fresh = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        late = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        BloodRequest.objects.filter(pk=late.pk).update(created_at=timezone.now() - timedelta(days=1))
        with_hospital = set(still_with_hospital().values_list("pk", flat=True))
        with_admin = set(awaiting_timeout_review().values_list("pk", flat=True))
        self.assertEqual(with_hospital, {fresh.pk})
        self.assertEqual(with_admin, {late.pk})

    def test_a_verified_request_shows_to_the_admin_straight_away(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False, patient_name="Verified Patient")
        BloodRequest.objects.filter(pk=req.pk).update(is_verified=True)
        self.assertIn("Verified Patient", self.page("all"))

    def test_an_over_limit_request_waits_for_the_hospital_like_any_other(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False, patient_name="Many Units")
        BloodRequest.objects.filter(pk=req.pk).update(extra_review="pending")
        self.assertNotIn("Many Units", self.page("review"))
        BloodRequest.objects.filter(pk=req.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.assertIn("Many Units", self.page("review"))
