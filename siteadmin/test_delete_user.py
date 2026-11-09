"""An admin can delete a donor or patient account for good, with a typed confirmation."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.identity import cnic_fingerprint
from accounts.models import Identity, UserBlock
from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from hospitals.models import HospitalAccount
from siteadmin.models import AdminAction
from notifications.models import Notification

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class DeleteUserTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.admin = User.objects.create_user("boss", password="pw", is_staff=True)
        self.client.force_login(self.admin)
        self.person = User.objects.create_user("ali.raza", password="pw")
        self.donor = make_donor("Ali Raza", "O+", self.location, user=self.person)
        Identity.objects.create(user=self.person, cnic_hash=cnic_fingerprint("4210112345671"), last4="5671")

    def delete(self, user=None, confirm=None):
        user = user or self.person
        return self.client.post(
            reverse("siteadmin:user_delete", args=[user.pk]),
            {"confirm_username": user.username if confirm is None else confirm, "next": reverse("siteadmin:users")},
        )

    def test_the_account_and_everything_on_it_is_removed(self):
        mine = make_request(self.person, self.location, hospital=self.hospital)
        someone = User.objects.create_user("someone", password="pw")
        theirs = make_request(someone, self.location, hospital=self.hospital, blood_type="O+")
        DonorResponse.objects.create(request=theirs, donor=self.donor)
        UserBlock.objects.create(user=self.person, reason="test", blocked_by=self.admin)
        Notification.objects.create(user=self.person, kind=Notification.FULFILLED, message="hello")
        response = self.delete()
        self.assertRedirects(response, reverse("siteadmin:users"))
        self.assertFalse(User.objects.filter(pk=self.person.pk).exists())
        self.assertFalse(Identity.objects.exists())
        self.assertFalse(BloodRequest.objects.filter(pk=mine.pk).exists())
        self.assertFalse(Notification.objects.filter(message="hello").exists())
        self.assertEqual(DonorResponse.objects.count(), 0)
        # Other people's requests stay.
        self.assertTrue(BloodRequest.objects.filter(pk=theirs.pk).exists())
        self.assertTrue(User.objects.filter(pk=someone.pk).exists())

    def test_a_patient_only_account_can_be_deleted_too(self):
        patient = User.objects.create_user("family", password="pw")
        make_request(patient, self.location, hospital=self.hospital)
        self.delete(patient)
        self.assertFalse(User.objects.filter(pk=patient.pk).exists())

    def test_the_wrong_confirmation_deletes_nothing(self):
        for typed in ("", "ali", "ALI.RAZA", "someone else"):
            with self.subTest(typed=typed):
                self.delete(confirm=typed)
                self.assertTrue(User.objects.filter(pk=self.person.pk).exists())
        self.assertFalse(AdminAction.objects.filter(action=AdminAction.DELETED_USER).exists())

    def test_the_audit_log_keeps_the_username_but_nothing_personal(self):
        make_request(self.person, self.location, hospital=self.hospital)
        self.delete()
        entry = AdminAction.objects.get(action=AdminAction.DELETED_USER)
        self.assertEqual(entry.actor, self.admin)
        self.assertIn("ali.raza", entry.target)
        self.assertIn("1 request", entry.target)
        text = f"{entry.target} {entry.note}"
        for private in ("03001234567", "4210112345671", "5671"):
            self.assertNotIn(private, text)

    def test_an_admin_cannot_delete_themselves_another_admin_or_a_hospital_desk(self):
        other_admin = User.objects.create_user("boss2", password="pw", is_staff=True)
        desk_user = User.objects.create_user("civil", password="pw")
        HospitalAccount.objects.create(user=desk_user, hospital=self.hospital, staff_name="Dr. Test")
        for target in (self.admin, other_admin, desk_user):
            with self.subTest(target=target.username):
                self.client.force_login(self.admin)
                self.delete(target)
                self.assertTrue(User.objects.filter(pk=target.pk).exists())

    def test_a_get_cannot_delete(self):
        response = self.client.get(reverse("siteadmin:user_delete", args=[self.person.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(User.objects.filter(pk=self.person.pk).exists())

    def test_a_signed_in_non_admin_is_refused(self):
        self.client.force_login(User.objects.create_user("nobody", password="pw"))
        self.assertEqual(self.delete().status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.person.pk).exists())

    def test_the_users_page_has_a_delete_button_and_the_confirmation_box(self):
        page = self.client.get(reverse("siteadmin:users")).content.decode()
        self.assertIn("data-delete-user", page)
        self.assertIn("Are you sure you want to permanently delete this account?", page)
        self.assertIn(reverse("siteadmin:user_delete", args=[self.person.pk]), page)
        self.assertIn('name="confirm_username"', page)

    def test_staff_and_hospital_rows_have_no_delete_button(self):
        desk_user = User.objects.create_user("civil", password="pw")
        HospitalAccount.objects.create(user=desk_user, hospital=self.hospital, staff_name="Dr. Test")
        page = self.client.get(reverse("siteadmin:users")).content.decode()
        self.assertNotIn(reverse("siteadmin:user_delete", args=[desk_user.pk]), page)
        self.assertNotIn(reverse("siteadmin:user_delete", args=[self.admin.pk]), page)
