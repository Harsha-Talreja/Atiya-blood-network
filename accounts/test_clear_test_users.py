from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from accounts.identity import cnic_fingerprint
from accounts.models import Identity, RetiredCnic
from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from hospitals.models import Hospital, HospitalAccount

User = get_user_model()


class ClearTestUsers(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.admin = User.objects.create_superuser("boss", password="pw")
        self.staff = User.objects.create_user("staffer", password="pw", is_staff=True)
        self.desk = User.objects.create_user("deskx", password="pw")
        HospitalAccount.objects.create(user=self.desk, hospital=self.hospital)
        self.person = User.objects.create_user("ali", password="pw")
        self.donor = make_donor("Ali", "O+", self.location, user=self.person)
        Identity.objects.create(user=self.person, cnic_hash=cnic_fingerprint("4210112345671"), last4="5671")
        self.family = User.objects.create_user("family", password="pw")
        self.req = make_request(self.family, self.location, hospital=self.hospital)
        DonorResponse.objects.create(request=self.req, donor=self.donor)
        RetiredCnic.objects.create(cnic_hash="x" * 64)

    def run_it(self, *args):
        out = StringIO()
        call_command("clear_test_users", *args, stdout=out)
        return out.getvalue()

    def test_without_yes_nothing_is_deleted(self):
        text = self.run_it()
        self.assertIn("Nothing deleted", text)
        self.assertTrue(User.objects.filter(username="ali").exists())

    def test_with_yes_only_donors_and_patients_go(self):
        self.run_it("--yes")
        self.assertFalse(User.objects.filter(username__in=["ali", "family"]).exists())
        self.assertEqual(BloodRequest.objects.count(), 0)
        self.assertEqual(DonorResponse.objects.count(), 0)
        self.assertEqual(Identity.objects.count(), 0)
        self.assertEqual(RetiredCnic.objects.count(), 0)
        self.assertTrue(User.objects.filter(username__in=["boss", "staffer", "deskx"]).count() == 3)
        self.assertTrue(HospitalAccount.objects.filter(user=self.desk).exists())
        self.assertTrue(Hospital.objects.filter(pk=self.hospital.pk).exists())
