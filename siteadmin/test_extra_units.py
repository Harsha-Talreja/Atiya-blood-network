"""Admin review of requests that asked for more than the unit limit."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.selectors import open_requests
from blood_requests.services import requests_posted_today
from blood_requests.tests import make_hospital, make_location, make_request
from core.constants import EXTRA_APPROVED, EXTRA_PENDING, EXTRA_REJECTED, STATUS_PENDING, STATUS_REJECTED
from siteadmin.models import AdminAction, SiteSetting

User = get_user_model()
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
REASON = "Patient is going into open-heart surgery and the surgeon has asked for six units."


@FAST_HASHER
class ReviewTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.staff = User.objects.create_user("boss", password="pw", is_staff=True)
        self.poster = User.objects.create_user("poster", password="pw")
        self.req = make_request(
            self.poster, self.location, hospital=self.hospital, units_needed=6,
            extra_reason=REASON, is_verified=False,
        )
        # The hospital did not act within its wait, so the admin has it. (A request still
        # inside that wait belongs to the hospital: see HospitalFirstTests below.)
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(minutes=30))
        self.req.refresh_from_db()
        self.url = reverse("siteadmin:request_review", args=[self.req.pk])
        self.client.force_login(self.staff)

    def decide(self, decision, note=""):
        return self.client.post(self.url, {"decision": decision, "note": note})

    # --------------------------------------------------------- reading it

    def test_the_review_page_shows_the_reason_and_the_limit(self):
        page = self.client.get(self.url)
        self.assertContains(page, REASON)
        self.assertContains(page, "limit 4")
        self.assertContains(page, "Approve")
        self.assertContains(page, "Reject")

    def test_the_requests_page_lists_it_under_extra_units(self):
        page = self.client.get(reverse("siteadmin:requests") + "?state=review")
        self.assertContains(page, "Waiting for an admin to approve 6 units")
        self.assertContains(page, self.url)

    def test_the_overview_and_the_side_panel_flag_it(self):
        page = self.client.get(reverse("siteadmin:overview"))
        self.assertContains(page, "Extra units to approve")
        self.assertContains(page, self.url)
        self.assertContains(page, "waiting for your decision")

    def test_the_pending_request_is_not_in_the_unchecked_queue(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(days=1))
        page = self.client.get(reverse("siteadmin:requests") + "?state=unchecked")
        self.assertNotContains(page, "poster")

    # --------------------------------------------------------- approving

    def test_approving_records_who_when_and_why(self):
        self.decide("approve", "Confirmed with the ward by phone.")
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_APPROVED)
        self.assertEqual(self.req.reviewed_by, self.staff)
        self.assertIsNotNone(self.req.reviewed_at)
        self.assertEqual(self.req.review_note, "Confirmed with the ward by phone.")
        entry = AdminAction.objects.get()
        self.assertEqual(entry.action, AdminAction.APPROVED_EXTRA_UNITS)
        self.assertEqual(entry.note, "Confirmed with the ward by phone.")

    def test_an_approval_note_is_optional(self):
        self.decide("approve")
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_APPROVED)

    def test_approving_after_the_hospital_missed_its_wait_lets_donors_see_it_unverified(self):
        """The admin only gets the request because the hospital did not act, so approving
        releases it, labelled as admin-approved and never as hospital-verified."""
        self.decide("approve", "ok")
        self.req.refresh_from_db()
        self.assertFalse(self.req.is_verified)
        self.assertTrue(self.req.released_early)
        self.assertIn(self.req, open_requests())
        self.assertIn("not hospital verified", self.req.release_label.lower().replace("-", " ").replace("  ", " "))

    def test_an_approved_and_hospital_verified_request_goes_out_at_once(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(is_verified=True)
        self.decide("approve", "ok")
        self.req.refresh_from_db()
        self.assertIn(self.req, open_requests())

    def test_approving_restarts_the_deadline_it_lost_while_hidden(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        self.decide("approve", "ok")
        self.req.refresh_from_db()
        self.assertGreater(self.req.expires_at, timezone.now() + timedelta(hours=60))

    # --------------------------------------------------------- rejecting

    def test_rejecting_needs_a_note(self):
        response = self.decide("reject", "")
        self.assertContains(response, "Please say why this is being rejected.")
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_PENDING)
        self.assertFalse(AdminAction.objects.exists())

    def test_rejecting_closes_it_and_keeps_it_off_the_board(self):
        self.decide("reject", "Not supported by the hospital's blood bank.")
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_REJECTED)
        self.assertEqual(self.req.status, STATUS_REJECTED)
        self.assertFalse(self.req.is_open)
        self.assertNotIn(self.req, open_requests())
        self.assertEqual(AdminAction.objects.get().action, AdminAction.REJECTED_EXTRA_UNITS)

    def test_a_rejected_request_still_counts_toward_the_daily_limit(self):
        self.decide("reject", "Not supported by the hospital's blood bank.")
        self.assertEqual(requests_posted_today(self.poster), 1)

    def test_the_requester_sees_the_decision_and_the_note(self):
        self.decide("reject", "Not supported by the hospital's blood bank.")
        self.client.force_login(self.poster)
        page = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        self.assertContains(page, "Extra units not approved")
        self.assertContains(page, "Not supported by the hospital")
        self.assertContains(self.client.get(reverse("blood_requests:mine")), "Rejected")

    def test_the_requester_sees_that_it_is_waiting(self):
        self.client.force_login(self.poster)
        page = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        self.assertContains(page, "Waiting for an admin to approve the extra units")

    # ------------------------------------------------------- guard rails

    def test_a_decision_is_made_once(self):
        self.decide("approve", "first")
        self.decide("reject", "changed my mind")
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_APPROVED)
        self.assertEqual(AdminAction.objects.count(), 1)

    def test_a_non_staff_user_cannot_decide(self):
        self.client.force_login(self.poster)
        self.assertEqual(self.decide("approve", "me").status_code, 403)
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_PENDING)

    def test_the_hospital_cannot_approve_either(self):
        from hospitals.models import HospitalAccount

        desk = User.objects.create_user("civil_desk", password="pw")
        HospitalAccount.objects.create(user=desk, hospital=self.hospital, staff_name="Desk")
        self.client.force_login(desk)
        self.assertEqual(self.decide("approve", "x").status_code, 403)

    def test_an_unknown_decision_is_ignored(self):
        self.decide("maybe", "x")
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_PENDING)


@FAST_HASHER
class SettingsTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("boss", password="pw", is_staff=True)
        self.client.force_login(self.staff)
        self.url = reverse("siteadmin:settings")

    def save(self, **extra):
        data = {"critical_wait_minutes": 1, "urgent_wait_minutes": 1, "normal_wait_minutes": 1}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_the_unit_limit_can_be_changed_and_is_logged(self):
        self.save(max_units_per_request=6)
        self.assertEqual(SiteSetting.load().max_units_per_request, 6)
        self.assertIn("6 units per request", AdminAction.objects.get().target)

    def test_leaving_it_out_keeps_the_current_value(self):
        row = SiteSetting.load()
        row.max_units_per_request = 5
        row.save()
        self.save()
        self.assertEqual(SiteSetting.load().max_units_per_request, 5)

    def test_zero_and_too_many_are_refused(self):
        for bad in (0, 21):
            self.save(max_units_per_request=bad)
            self.assertEqual(SiteSetting.load().max_units_per_request, 4)

    def test_the_default_is_four(self):
        self.assertEqual(SiteSetting.load().max_units_per_request, 4)

    def test_the_page_has_the_field(self):
        self.assertContains(self.client.get(self.url), "Units per request before approval is needed")


@FAST_HASHER
class HospitalFirstTests(TestCase):
    """A hospital that verifies an over-limit request accepts its extra units too."""

    def setUp(self):
        from hospitals.models import HospitalAccount
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.staff = User.objects.create_user("boss", password="pw", is_staff=True)
        self.poster = User.objects.create_user("poster", password="pw")
        self.desk = User.objects.create_user("deskperson", password="pw")
        HospitalAccount.objects.create(user=self.desk, hospital=self.hospital, staff_name="Desk")
        self.req = make_request(
            self.poster, self.location, hospital=self.hospital, units_needed=6,
            extra_reason=REASON, is_verified=False,
        )

    def test_the_admin_does_not_see_it_while_the_hospital_is_still_inside_its_wait(self):
        from blood_requests.selectors import awaiting_extra_review, still_with_hospital
        self.assertNotIn(self.req, awaiting_extra_review())
        self.assertIn(self.req, still_with_hospital())
        self.client.force_login(self.staff)
        page = self.client.get(reverse("siteadmin:requests") + "?state=review")
        self.assertNotContains(page, "Test Patient")

    def test_the_hospital_verifying_accepts_the_extra_units_and_donors_see_it(self):
        from blood_requests.services import verify_by_hospital
        verify_by_hospital(self.desk, self.req.pk)
        self.req.refresh_from_db()
        self.assertEqual(self.req.extra_review, EXTRA_APPROVED)
        self.assertEqual(self.req.reviewed_by, self.desk)
        self.assertTrue(self.req.extra_accepted_by_hospital)
        self.assertIn(self.req, open_requests())

    def test_it_never_reaches_the_admin_after_the_hospital_verified(self):
        from blood_requests.selectors import awaiting_extra_review
        from blood_requests.services import verify_by_hospital
        verify_by_hospital(self.desk, self.req.pk)
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.assertNotIn(self.req, awaiting_extra_review())

    def test_the_hospital_desk_button_works_for_it_and_says_donors_can_see_it(self):
        self.client.force_login(self.desk)
        response = self.client.post(reverse("hospitals:verify", args=[self.req.pk]), follow=True)
        self.assertContains(response, "now visible to donors")

    def test_the_requester_is_told_the_hospital_accepted_the_units(self):
        from blood_requests.services import verify_by_hospital
        verify_by_hospital(self.desk, self.req.pk)
        self.client.force_login(self.poster)
        page = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        self.assertContains(page, "Extra units accepted")
        self.assertContains(page, "The hospital verified this request")

    def test_while_the_hospital_has_it_the_requester_is_told_to_wait_for_the_hospital(self):
        self.client.force_login(self.poster)
        page = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        self.assertContains(page, "Waiting for the hospital to verify")
        self.assertNotContains(page, "Waiting for an admin to approve the extra units")

    def test_after_the_wait_it_goes_to_the_admin_and_admins_are_told_once(self):
        from blood_requests.selectors import awaiting_extra_review
        from blood_requests.services import escalate_overdue_requests
        from notifications.models import Notification
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.assertIn(self.req, awaiting_extra_review())
        self.assertFalse(Notification.objects.filter(user=self.staff, kind=Notification.NEEDS_REVIEW).exists())
        escalate_overdue_requests()
        escalate_overdue_requests()
        self.assertEqual(Notification.objects.filter(user=self.staff, kind=Notification.NEEDS_REVIEW).count(), 1)
