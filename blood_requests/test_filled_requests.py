"""Once enough donors have offered for the units asked, other donors are not shown the request."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.models import DonorResponse
from blood_requests.selectors import requests_for_donor
from blood_requests.tests import make_donor, make_hospital, make_location, make_request

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FilledRequests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.family = User.objects.create_user(username="family", password="x")
        self.first = make_donor("First Donor", "O+", self.location)
        self.second = make_donor("Second Donor", "O+", self.location)

    def request(self, units=1):
        return make_request(self.family, self.location, hospital=self.hospital, blood_type="A+", units_needed=units)

    def respond(self, donor, req):
        self.client.force_login(donor.user)
        return self.client.post(reverse("blood_requests:respond", args=[req.pk]), follow=True)

    def test_a_one_unit_request_disappears_from_other_donors_once_someone_offers(self):
        req = self.request()
        self.assertIn(req, requests_for_donor(self.second))
        self.respond(self.first, req)
        self.assertNotIn(req, requests_for_donor(self.second))

    def test_the_donor_who_offered_still_sees_it(self):
        req = self.request()
        self.respond(self.first, req)
        self.assertIn(req, requests_for_donor(self.first))

    def test_a_second_donor_cannot_offer_on_a_full_request(self):
        req = self.request()
        self.respond(self.first, req)
        response = self.respond(self.second, req)
        self.assertContains(response, "Another donor has already offered")
        self.assertEqual(DonorResponse.objects.filter(request=req).count(), 1)

    def test_the_page_tells_the_second_donor_instead_of_offering_the_button(self):
        req = self.request()
        DonorResponse.objects.create(request=req, donor=self.first)
        self.client.force_login(self.second.user)
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertNotIn(">I can help<", html)
        self.assertIn("Another donor has already offered", html)

    def test_the_unit_count_makes_no_difference(self):
        third = make_donor("Third Donor", "O+", self.location)
        req = self.request(units=3)
        self.respond(self.first, req)
        self.assertNotIn(req, requests_for_donor(self.second))
        self.assertContains(self.respond(third, req), "Another donor has already offered")
        self.assertEqual(DonorResponse.objects.filter(request=req).count(), 1)

    def test_it_opens_again_when_an_offer_is_withdrawn(self):
        req = self.request()
        self.respond(self.first, req)
        self.assertNotIn(req, requests_for_donor(self.second))
        self.client.force_login(self.first.user)
        self.client.post(reverse("blood_requests:withdraw", args=[req.pk]))
        self.assertIn(req, requests_for_donor(self.second))
        self.assertContains(self.respond(self.second, req), "willing to help")

    def test_the_dashboard_list_shows_the_difference(self):
        req = self.request()
        DonorResponse.objects.create(request=req, donor=self.first)
        self.client.force_login(self.second.user)
        self.assertNotIn(reverse("blood_requests:detail", args=[req.pk]),
                         self.client.get(reverse("donors:profile")).content.decode())
