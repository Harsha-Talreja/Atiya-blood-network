"""The real forms, end to end, for a request that asks for more units than the limit."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.models import BloodRequest
from blood_requests.selectors import requests_for_donor
from blood_requests.test_views import request_form_data
from blood_requests.tests import make_donor, make_hospital, make_location
from hospitals.models import HospitalAccount

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ExtraUnitsEndToEnd(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.family = User.objects.create_user("family", password="pw")
        self.desk = User.objects.create_user("deskperson", password="pw")
        HospitalAccount.objects.create(user=self.desk, hospital=self.hospital, staff_name="Desk")
        self.admin = User.objects.create_user("boss", password="pw", is_staff=True)
        self.donor = make_donor("Helper", "O-", self.location)

    def post_request(self):
        self.client.force_login(self.family)
        data = request_form_data(self.hospital, units_needed=6, extra_reason="Open-heart surgery, the surgeon asked for six units.")
        self.client.post(reverse("blood_requests:new"), data, follow=True)
        return BloodRequest.objects.get(requester=self.family)

    def test_hospital_verifies_and_donors_see_it_with_no_admin_involved(self):
        req = self.post_request()
        self.assertEqual(req.extra_review, "pending")
        # Nobody but the hospital has it yet.
        self.assertNotIn(req, requests_for_donor(self.donor))
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("siteadmin:requests") + "?state=review"), req.patient_name)
        self.assertNotContains(self.client.get(reverse("siteadmin:overview")), "Extra units to approve")
        # The hospital's own desk verifies it.
        self.client.force_login(self.desk)
        self.assertContains(self.client.get(reverse("hospitals:dashboard")), "also accepts the extra units")
        self.client.post(reverse("hospitals:verify", args=[req.pk]))
        self.assertIn(req, requests_for_donor(self.donor))
        # And the donor can say yes.
        self.client.force_login(self.donor.user)
        page = self.client.post(reverse("blood_requests:respond", args=[req.pk]), follow=True)
        self.assertContains(page, "willing to help")
