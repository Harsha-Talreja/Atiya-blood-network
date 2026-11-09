"""Who may read a patient's phone number, and a donor's.

The number is shown to the person who posted the request, the hospital it names,
admins, and donors who have offered to help. Not to everyone who is signed in.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from blood_requests.models import DonorResponse
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from hospitals.models import HospitalAccount

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
PHONE = "03007776655"


@FAST_HASHER
class PatientContactPrivacy(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.other_hospital = make_hospital("Other Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(
            self.owner, self.location, hospital=self.hospital, blood_type="A+", contact_phone=PHONE,
        )
        self.url = reverse("blood_requests:detail", args=[self.req.pk])

    def page(self, user=None):
        self.client.logout()
        if user is not None:
            self.client.force_login(user)
        return self.client.get(self.url).content.decode()

    def test_anonymous_visitors_do_not_see_it(self):
        self.assertNotIn(PHONE, self.page())

    def test_an_ordinary_signed_in_user_does_not_see_it(self):
        viewer = User.objects.create_user(username="viewer", password="x")
        html = self.page(viewer)
        self.assertNotIn(PHONE, html)
        self.assertIn("shown to the requester, the hospital and donors who offer to help", html)

    def test_a_donor_who_has_not_offered_does_not_see_it(self):
        user = User.objects.create_user(username="donor", password="x")
        make_donor("Donor", "O-", self.location, user=user)
        self.assertNotIn(PHONE, self.page(user))

    def test_the_requester_sees_it(self):
        self.assertIn(PHONE, self.page(self.owner))

    def test_an_admin_sees_it(self):
        admin = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.assertIn(PHONE, self.page(admin))

    def test_staff_of_the_named_hospital_see_it(self):
        desk = User.objects.create_user(username="desk", password="x")
        HospitalAccount.objects.create(user=desk, hospital=self.hospital, staff_name="Desk")
        self.assertIn(PHONE, self.page(desk))

    def test_staff_of_a_different_hospital_do_not(self):
        desk = User.objects.create_user(username="otherdesk", password="x")
        HospitalAccount.objects.create(user=desk, hospital=self.other_hospital, staff_name="Desk")
        self.assertNotIn(PHONE, self.page(desk))

    def test_a_donor_sees_it_once_they_have_offered_and_not_before(self):
        user = User.objects.create_user(username="donor", password="x")
        donor = make_donor("Donor", "O-", self.location, user=user)
        self.assertNotIn(PHONE, self.page(user))
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertTrue(DonorResponse.objects.filter(donor=donor).exists())
        self.assertIn(PHONE, self.page(user))

    def test_a_refused_donor_never_gets_the_number(self):
        user = User.objects.create_user(username="wrongtype", password="x")
        make_donor("Wrong", "B+", self.location, user=user)  # B+ cannot give to A+
        self.client.force_login(user)
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertNotIn(PHONE, self.page(user))

    def test_the_number_is_not_on_the_board_the_home_page_or_the_my_requests_of_others(self):
        viewer = User.objects.create_user(username="viewer", password="x")
        self.client.force_login(viewer)
        for name in ("blood_requests:list", "core:home", "blood_requests:mine"):
            with self.subTest(page=name):
                self.assertNotIn(PHONE, self.client.get(reverse(name)).content.decode())

    def test_a_request_nobody_released_is_not_even_openable_by_strangers(self):
        hidden = make_request(
            self.owner, self.location, hospital=self.hospital, is_verified=False, contact_phone=PHONE,
        )
        viewer = User.objects.create_user(username="viewer", password="x")
        self.client.force_login(viewer)
        response = self.client.get(reverse("blood_requests:detail", args=[hidden.pk]))
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("blood_requests:detail", args=[hidden.pk])).status_code, 200)


@FAST_HASHER
class DonorPhoneConsent(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+")

    def offer(self, name, consent):
        user = User.objects.create_user(username=name, password="x")
        donor = make_donor(name, "O-", self.location, user=user)
        donor.phone = "0300" + str(abs(hash(name)) % 10**7).zfill(7)
        donor.phone_consent = consent
        donor.save()
        DonorResponse.objects.create(request=self.req, donor=donor)
        return donor

    def test_the_requester_sees_only_the_numbers_donors_agreed_to_share(self):
        yes = self.offer("sharing", True)
        no = self.offer("private", False)
        self.client.force_login(self.owner)
        html = self.client.get(reverse("blood_requests:detail", args=[self.req.pk])).content.decode()
        self.assertIn(yes.phone, html)
        self.assertNotIn(no.phone, html)
        self.assertIn("Number not shared", html)

    def test_other_donors_never_see_who_offered(self):
        donor = self.offer("sharing", True)
        viewer = User.objects.create_user(username="viewer", password="x")
        make_donor("Viewer", "O-", self.location, user=viewer)
        self.client.force_login(viewer)
        html = self.client.get(reverse("blood_requests:detail", args=[self.req.pk])).content.decode()
        self.assertNotIn(donor.phone, html)
        self.assertNotIn("Donors who offered", html)
