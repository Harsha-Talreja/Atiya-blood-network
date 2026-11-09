import csv
import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.tests import make_donor, make_hospital, make_location, make_request

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class RequestsCsvTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.boss = User.objects.create_user("boss", password="x", is_staff=True)
        self.poster = User.objects.create_user("poster", password="x")
        self.client.force_login(self.boss)
        self.url = reverse("siteadmin:requests_export")

    def rows(self, query=""):
        response = self.client.get(self.url + query)
        text = response.content.decode("utf-8-sig")
        return response, list(csv.reader(io.StringIO(text)))

    def test_it_is_a_csv_download_with_a_header_row(self):
        make_request(self.poster, self.location, hospital=self.hospital)
        response, rows = self.rows()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(rows[0][:3], ["ID", "Patient", "Blood type"])
        self.assertEqual(len(rows), 2)

    def test_a_row_describes_the_request_honestly(self):
        verified = make_request(self.poster, self.location, hospital=self.hospital, patient_name="Verified One")
        released = make_request(self.poster, self.location, hospital=self.hospital, patient_name="Released One",
                                is_verified=False, released_early=True)
        waiting = make_request(self.poster, self.location, hospital=self.hospital, patient_name="Waiting One",
                               is_verified=False)
        late = make_request(self.poster, self.location, hospital=self.hospital, patient_name="Late One",
                            is_verified=False)
        BloodRequest.objects.filter(pk=late.pk).update(created_at=timezone.now() - timedelta(days=1))
        _, rows = self.rows()
        state = {r[1]: r[7] for r in rows[1:]}
        self.assertEqual(state["Verified One"], "Live, hospital verified")
        self.assertEqual(state["Released One"], "Live, Admin released — not hospital verified")
        self.assertEqual(state["Late One"], "Hospital missed deadline, waiting for admin")
        # Still inside the hospital's wait: not the admin's yet, so not in the file.
        self.assertNotIn("Waiting One", state)

    def test_offers_are_counted(self):
        req = make_request(self.poster, self.location, hospital=self.hospital)
        DonorResponse.objects.create(request=req, donor=make_donor("d1", "O-", self.location))
        _, rows = self.rows()
        self.assertEqual(rows[1][-1], "1")

    def test_patient_phone_numbers_are_not_in_the_file(self):
        make_request(self.poster, self.location, hospital=self.hospital, contact_phone="03007770001")
        response, _ = self.rows()
        self.assertNotIn("03007770001", response.content.decode("utf-8-sig"))

    def test_it_follows_the_tab_and_the_search(self):
        make_request(self.poster, self.location, hospital=self.hospital, patient_name="Alpha")
        make_request(self.poster, self.location, hospital=self.hospital, patient_name="Beta", status="Fulfilled")
        _, rows = self.rows("?state=fulfilled")
        self.assertEqual([r[1] for r in rows[1:]], ["Beta"])
        _, rows = self.rows("?q=alp")
        self.assertEqual([r[1] for r in rows[1:]], ["Alpha"])

    def test_a_name_that_looks_like_a_formula_is_defused(self):
        make_request(self.poster, self.location, hospital=self.hospital, patient_name="=HYPERLINK(\"http://x\")")
        _, rows = self.rows()
        self.assertTrue(rows[1][1].startswith("'="))

    def test_an_ordinary_user_and_a_visitor_cannot_download(self):
        for user in (self.poster, None):
            self.client.logout()
            if user:
                self.client.force_login(user)
            response = self.client.get(self.url)
            self.assertNotEqual(response.status_code, 200)

    def test_the_requests_page_has_the_download_button_keeping_the_tab(self):
        html = self.client.get(reverse("siteadmin:requests") + "?state=live").content.decode()
        self.assertIn("Download CSV", html)
        self.assertIn("requests/export.csv?state=live", html)
