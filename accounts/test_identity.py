"""The CNIC is asked once, on the donor form and the request form, and is not stored as typed."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.identity import cnic_fingerprint, get_identity
from accounts.models import Identity
from blood_requests.models import BloodRequest
from blood_requests.test_views import request_form_data
from blood_requests.tests import make_hospital, make_location
from donors.models import DonorProfile
from donors.test_views import form_data

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
CNIC = "4210112345671"


@FAST_HASHER
class DonorFormCnicTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("ali", "ali@example.com", "x")
        self.client.force_login(self.user)
        self.area = make_location("Sukkur", "Military Road")
        self.url = reverse("donors:edit")

    def test_the_form_asks_for_a_13_digit_cnic_shown_with_dashes(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="cnic"', html)
        self.assertIn('maxlength="15"', html)          # 13 digits and the 2 dashes
        self.assertIn('data-digits="13"', html)        # the count and the limit are of digits
        self.assertIn('data-format="cnic"', html)
        self.assertIn('placeholder="12345-1234567-1"', html)
        self.assertIn('inputmode="numeric"', html)

    def test_the_two_old_texts_are_gone_from_the_cnic_box(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn("13 digits, no dashes", html)
        self.assertNotIn("Asked once", html)

    def test_a_cnic_typed_with_dashes_is_saved_as_the_13_digits(self):
        self.assertEqual(self.client.post(self.url, form_data(self.area, cnic="42101-1234567-1")).status_code, 302)
        self.assertEqual(get_identity(self.user).last4, "5671")
        self.assertEqual(get_identity(self.user).cnic_hash, cnic_fingerprint(CNIC))

    def test_a_donor_cannot_register_without_the_cnic(self):
        response = self.client.post(self.url, form_data(self.area, omit=("cnic",)))
        self.assertEqual(response.status_code, 200)
        self.assertIn("cnic", response.context["form"].errors)
        self.assertFalse(DonorProfile.objects.exists())
        self.assertFalse(Identity.objects.exists())

    def test_only_exactly_13_digits_are_accepted(self):
        for bad in ("421011234567", "42101123456712", "42101 1234567", "abcdefghijklm", "4210112345 71",
                    "4210-11234567-1", "42101-12345671", "421011234567-1", "42101-1234567-12", "42101--1234567"):
            with self.subTest(cnic=bad):
                response = self.client.post(self.url, form_data(self.area, cnic=bad))
                self.assertIn("cnic", response.context["form"].errors)
                self.assertFalse(DonorProfile.objects.exists())
        response = self.client.post(self.url, form_data(self.area, cnic=CNIC))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DonorProfile.objects.exists())

    def test_the_cnic_is_kept_as_a_fingerprint_and_last_four_digits_only(self):
        self.client.post(self.url, form_data(self.area, cnic=CNIC))
        identity = Identity.objects.get(user=self.user)
        self.assertEqual(identity.last4, "5671")
        self.assertEqual(identity.cnic_hash, cnic_fingerprint(CNIC))
        self.assertNotIn(CNIC, (identity.cnic_hash, identity.last4))
        self.assertEqual(identity.masked, "•" * 9 + "5671")

    def test_it_is_asked_once_then_shown_masked(self):
        self.client.post(self.url, form_data(self.area, cnic=CNIC))
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('name="cnic"', html)
        self.assertIn("CNIC on file", html)
        self.assertIn("5671", html)
        self.assertNotIn(CNIC, html)
        # Saving the profile again needs no CNIC and leaves the saved one alone.
        response = self.client.post(self.url, form_data(self.area, omit=("cnic",), full_name="Ali R."))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Identity.objects.count(), 1)
        self.assertEqual(Identity.objects.get().last4, "5671")

    def test_a_cnic_already_used_by_another_account_is_refused(self):
        other = User.objects.create_user("sana", "s@example.com", "x")
        Identity.objects.create(user=other, cnic_hash=cnic_fingerprint(CNIC), last4=CNIC[-4:])
        response = self.client.post(self.url, form_data(self.area, cnic=CNIC))
        self.assertIn("already used by another account", str(response.context["form"].errors["cnic"]))
        self.assertFalse(DonorProfile.objects.exists())

    def test_the_details_page_shows_only_the_last_four(self):
        self.client.post(self.url, form_data(self.area, cnic=CNIC))
        page = self.client.get(reverse("donors:profile") + "?tab=details").content.decode()
        self.assertIn("5671", page)
        self.assertNotIn(CNIC, page)


@FAST_HASHER
class RequestFormCnicTests(TestCase):
    def setUp(self):
        self.area = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.area)
        self.user = User.objects.create_user("requester", password="x")
        self.client.force_login(self.user)
        self.url = reverse("blood_requests:new")

    def post(self, **overrides):
        return self.client.post(self.url, request_form_data(self.hospital, **overrides))

    def test_the_form_asks_for_a_13_digit_cnic(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="cnic"', html)
        self.assertIn('maxlength="15"', html)
        self.assertIn('data-format="cnic"', html)

    def test_a_request_cannot_be_posted_without_a_cnic(self):
        data = request_form_data(self.hospital)
        data.pop("cnic")
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("cnic", response.context["form"].errors)
        self.assertFalse(BloodRequest.objects.exists())

    def test_a_short_or_long_cnic_is_refused(self):
        for bad in ("421011234567", "42101123456712", "4210-11234567-1", "42101-12345671"):
            with self.subTest(cnic=bad):
                response = self.post(cnic=bad)
                self.assertIn("cnic", response.context["form"].errors)
        self.assertFalse(BloodRequest.objects.exists())

    def test_a_cnic_typed_with_dashes_is_accepted_on_the_request_form_too(self):
        self.assertEqual(self.post(cnic="42101-1234567-1").status_code, 302)
        self.assertEqual(get_identity(self.user).last4, "5671")

    def test_the_first_request_saves_the_cnic_and_later_ones_do_not_ask(self):
        self.assertEqual(self.post().status_code, 302)
        self.assertEqual(get_identity(self.user).last4, "5671")
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('name="cnic"', html)
        self.assertIn("CNIC on file", html)
        data = request_form_data(self.hospital)
        data.pop("cnic")
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(BloodRequest.objects.count(), 2)

    def test_one_cnic_serves_both_the_donor_and_the_request_form(self):
        self.post()
        donor_page = self.client.get(reverse("donors:edit")).content.decode()
        self.assertNotIn('name="cnic"', donor_page)
        self.assertIn("CNIC on file", donor_page)

    def test_a_cnic_used_by_another_account_cannot_be_reused_on_a_request(self):
        other = User.objects.create_user("other", password="x")
        Identity.objects.create(user=other, cnic_hash=cnic_fingerprint(CNIC), last4=CNIC[-4:])
        response = self.post()
        self.assertIn("cnic", response.context["form"].errors)
        self.assertFalse(BloodRequest.objects.exists())

    def test_the_contact_number_must_be_11_digits(self):
        for bad in ("+923001234567", "030012345678", "0300123456"):
            with self.subTest(phone=bad):
                response = self.post(contact_phone=bad)
                self.assertIn("contact_phone", response.context["form"].errors)
        self.assertContains(self.client.get(self.url), 'data-digits="11"')


@FAST_HASHER
class DeletedAccountCnicTests(TestCase):
    """When an admin deletes an account, its CNIC cannot be used to make a new one."""

    def setUp(self):
        from accounts.models import RetiredCnic
        self.RetiredCnic = RetiredCnic
        self.area = make_location("Sukkur", "Military Road")
        self.admin = User.objects.create_user("boss", password="x", is_staff=True)
        self.old = User.objects.create_user("old", "o@example.com", "x")
        self.client.force_login(self.old)
        self.client.post(reverse("donors:edit"), form_data(self.area, cnic=CNIC))
        self.assertTrue(Identity.objects.filter(user=self.old).exists())

    def delete_old(self):
        from siteadmin import services
        services.delete_user(self.admin, self.old)

    def test_deleting_the_account_keeps_only_a_fingerprint(self):
        self.delete_old()
        self.assertFalse(User.objects.filter(username="old").exists())
        self.assertFalse(Identity.objects.exists())
        row = self.RetiredCnic.objects.get()
        self.assertEqual(row.cnic_hash, cnic_fingerprint(CNIC))
        self.assertNotIn(CNIC, str(row.__dict__))
        self.assertEqual({f.name for f in self.RetiredCnic._meta.fields}, {"id", "cnic_hash", "retired_at"})

    def test_a_new_account_cannot_register_with_that_cnic_on_the_donor_form(self):
        self.delete_old()
        fresh = User.objects.create_user("fresh", "f@example.com", "x")
        self.client.force_login(fresh)
        response = self.client.post(reverse("donors:edit"), form_data(self.area, cnic=CNIC))
        self.assertIn("cnic", response.context["form"].errors)
        self.assertContains(response, "cannot be used again")
        self.assertFalse(DonorProfile.objects.filter(user=fresh).exists())

    def test_a_new_account_cannot_post_a_request_with_that_cnic(self):
        self.delete_old()
        fresh = User.objects.create_user("fresh", "f@example.com", "x")
        self.client.force_login(fresh)
        hospital = make_hospital("Civil Hospital", self.area)
        response = self.client.post(reverse("blood_requests:new"), request_form_data(hospital, cnic=CNIC))
        self.assertContains(response, "cannot be used again")
        self.assertFalse(BloodRequest.objects.exists())

    def test_a_different_cnic_still_works(self):
        self.delete_old()
        fresh = User.objects.create_user("fresh", "f@example.com", "x")
        self.client.force_login(fresh)
        self.client.post(reverse("donors:edit"), form_data(self.area, cnic="4210199999993"))
        self.assertTrue(DonorProfile.objects.filter(user=fresh).exists())

    def test_deleting_an_account_with_no_cnic_makes_no_row(self):
        from siteadmin import services
        plain = User.objects.create_user("plain", password="x")
        services.delete_user(self.admin, plain)
        self.assertFalse(self.RetiredCnic.objects.exists())

    def test_removing_the_row_lets_the_cnic_be_used_again(self):
        self.delete_old()
        self.RetiredCnic.objects.all().delete()
        fresh = User.objects.create_user("fresh", "f@example.com", "x")
        self.client.force_login(fresh)
        self.client.post(reverse("donors:edit"), form_data(self.area, cnic=CNIC))
        self.assertTrue(Identity.objects.filter(user=fresh).exists())

    def test_blocking_an_account_does_not_retire_the_cnic(self):
        from siteadmin import services
        services.block_user(self.admin, self.old)
        self.assertFalse(self.RetiredCnic.objects.exists())
