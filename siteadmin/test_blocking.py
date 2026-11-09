"""Blocking has to actually stop someone, not just label them.

A block that leaves the person's open requests on the donor board is worse than
no block at all, because the panel then says "Blocked" while donors are still
being sent to the post. These tests check the stopping, not the label.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserBlock, is_blocked
from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.selectors import open_requests
from blood_requests.tests import make_donor, make_hospital, make_location, make_request

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class BlockedUserTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.poster = User.objects.create_user("poster", password="pw")
        self.request_obj = make_request(self.poster, self.location, hospital=self.hospital)

    def block(self):
        return UserBlock.objects.create(user=self.poster, reason="repeated fakes")

    # ------------------------------------------------ the requests vanish

    def test_a_verified_request_leaves_the_board_when_its_poster_is_blocked(self):
        self.assertIn(self.request_obj, open_requests())
        self.block()
        self.assertNotIn(self.request_obj, open_requests())

    def test_the_model_property_agrees_with_the_queryset(self):
        """The two are twins; a block must fail both or neither."""
        self.assertTrue(self.request_obj.is_visible_to_donors)
        self.block()
        self.request_obj.refresh_from_db()
        self.assertFalse(self.request_obj.is_visible_to_donors)

    def test_blocking_beats_an_admin_approval(self):
        """A blocked person's request must not stay out because an admin approved it earlier."""
        req = make_request(
            self.poster, self.location, hospital=self.hospital, is_verified=False,
            released_early=True, timeout_review="approved",
        )
        self.assertTrue(req.is_visible_to_donors)

        self.block()
        req.refresh_from_db()
        self.assertFalse(req.is_visible_to_donors)
        self.assertNotIn(req, open_requests())

    def test_blocking_beats_an_early_release(self):
        req = make_request(
            self.poster, self.location, hospital=self.hospital,
            is_verified=False, released_early=True,
        )
        self.assertIn(req, open_requests())
        self.block()
        self.assertNotIn(req, open_requests())

    def test_unblocking_puts_the_requests_back(self):
        self.block()
        self.assertNotIn(self.request_obj, open_requests())
        UserBlock.objects.filter(user=self.poster).delete()
        self.assertIn(self.request_obj, open_requests())

    def test_the_public_board_page_itself_stops_showing_the_request(self):
        """Checked through the rendered page, not only the queryset, and by the
        request's own link - the cards are titled with the hospital, so looking
        for the patient or the username would pass whether blocking worked or
        not."""
        link = reverse("blood_requests:detail", args=[self.request_obj.pk])

        before = self.client.get(reverse("blood_requests:list"))
        self.assertContains(before, link)

        self.block()
        after = self.client.get(reverse("blood_requests:list"))
        self.assertNotContains(after, link)

    def test_other_peoples_requests_are_untouched(self):
        someone_else = User.objects.create_user("innocent")
        theirs = make_request(someone_else, self.location, hospital=self.hospital)
        self.block()
        self.assertIn(theirs, open_requests())

    # ----------------------------------------------- the person is stopped

    def test_a_blocked_user_cannot_open_the_post_a_request_form(self):
        self.block()
        self.client.force_login(self.poster)
        response = self.client.get(reverse("blood_requests:new"))
        self.assertEqual(response.status_code, 302)

    def test_a_blocked_user_cannot_post_a_request(self):
        self.block()
        self.client.force_login(self.poster)
        before = BloodRequest.objects.count()
        self.client.post(reverse("blood_requests:new"), {
            "patient_name": "Someone", "blood_type": "A+", "units_needed": 1,
            "urgency": "Normal", "hospital": self.hospital.pk,
            "contact_phone": "03001234567", "note": "",
        })
        self.assertEqual(BloodRequest.objects.count(), before)

    def test_a_blocked_donor_cannot_offer_to_help(self):
        donor_user = User.objects.create_user("helper", password="pw")
        make_donor("Helper", "O-", self.location, user=donor_user)
        UserBlock.objects.create(user=donor_user)

        self.client.force_login(donor_user)
        self.client.post(reverse("blood_requests:respond", args=[self.request_obj.pk]))
        self.assertFalse(DonorResponse.objects.exists())

    def test_a_blocked_user_cannot_sign_in(self):
        self.block()
        response = self.client.post(reverse("accounts:login"), {"username": "poster", "password": "pw"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "has been blocked by an admin")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_wrong_password_does_not_reveal_that_the_account_is_blocked(self):
        self.block()
        response = self.client.post(reverse("accounts:login"), {"username": "poster", "password": "nope"})
        self.assertNotContains(response, "blocked")

    def test_someone_already_signed_in_is_signed_out_when_blocked(self):
        self.client.force_login(self.poster)
        self.block()
        response = self.client.get(reverse("blood_requests:mine"))
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unblocking_lets_them_sign_in_again(self):
        self.block()
        UserBlock.objects.filter(user=self.poster).delete()
        response = self.client.post(reverse("accounts:login"), {"username": "poster", "password": "pw"})
        self.assertEqual(response.status_code, 302)

    def test_staff_are_never_signed_out_by_the_block_check(self):
        staff = User.objects.create_user("boss", password="pw", is_staff=True)
        UserBlock.objects.create(user=staff)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("siteadmin:overview")).status_code, 200)

    # ------------------------------------------------------ the helper

    def test_is_blocked_is_safe_to_call_with_an_anonymous_visitor(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(is_blocked(AnonymousUser()))
        self.assertFalse(is_blocked(None))
