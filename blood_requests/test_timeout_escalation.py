"""A hospital that misses its deadline does NOT release a request to donors.

The request moves to the admin's review queue; an admin approves or rejects it,
or releases it early for an emergency. In every case it is labelled "not
hospital verified", and `is_verified` is only ever set by a real verification.

Time is simulated by backdating created_at with a queryset update (which
bypasses auto_now_add), so no test waits.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserBlock
from blood_requests.models import BloodRequest
from blood_requests.selectors import awaiting_timeout_review, open_requests
from blood_requests.services import escalate_overdue_requests
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from core.constants import (
    ADMIN_APPROVED_LABEL,
    ADMIN_RELEASED_LABEL,
    AUTO_APPROVE_AFTER_MINUTES,
    STATUS_FULFILLED,
    STATUS_REJECTED,
)
from hospitals.models import HospitalAccount
from notifications.models import Notification
from siteadmin.models import AdminAction

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])

RELEASED = "Admin released — not hospital verified."
APPROVED = "Admin approved — not hospital verified."


def posted_minutes_ago(request_obj, minutes):
    BloodRequest.objects.filter(pk=request_obj.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes)
    )
    request_obj.refresh_from_db()
    return request_obj


class Base(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")

    def unverified(self, minutes_old=0, **extra):
        req = make_request(
            self.owner, self.location, hospital=self.hospital, blood_type="O-",
            is_verified=False, **extra,
        )
        return posted_minutes_ago(req, minutes_old) if minutes_old else req

    def late(self, **extra):
        return self.unverified(AUTO_APPROVE_AFTER_MINUTES + 1, **extra)


class TimeoutRuleTests(Base):
    def test_the_labels_are_exactly_the_required_wording(self):
        self.assertEqual(ADMIN_RELEASED_LABEL, RELEASED)
        self.assertEqual(ADMIN_APPROVED_LABEL, APPROVED)

    def test_a_fresh_unverified_request_is_hidden_and_not_yet_late(self):
        req = self.unverified()
        self.assertFalse(req.is_visible_to_donors)
        self.assertFalse(req.needs_timeout_review)
        self.assertNotIn(req, awaiting_timeout_review())

    def test_just_before_the_deadline_it_is_not_late(self):
        req = self.unverified(AUTO_APPROVE_AFTER_MINUTES - 0.01)
        self.assertFalse(req.needs_timeout_review)

    def test_after_the_deadline_it_waits_for_an_admin_and_is_still_hidden(self):
        req = self.late()
        self.assertTrue(req.needs_timeout_review)
        self.assertIn(req, awaiting_timeout_review())
        # The point of the whole feature: lateness never releases a request.
        self.assertFalse(req.is_visible_to_donors)
        self.assertNotIn(req, open_requests())

    def test_the_deadline_is_the_posting_time_plus_the_wait(self):
        req = self.unverified()
        self.assertEqual(req.hospital_deadline, req.created_at + timedelta(minutes=AUTO_APPROVE_AFTER_MINUTES))

    def test_an_unsaved_request_has_no_deadline_and_does_not_crash(self):
        draft = BloodRequest(
            requester=self.owner, patient_name="X", blood_type="O-", units_needed=1,
            urgency="Normal", hospital=self.hospital, location=self.location, contact_phone="03001234567",
        )
        self.assertIsNone(draft.hospital_deadline)
        self.assertFalse(draft.needs_timeout_review)
        self.assertFalse(draft.is_visible_to_donors)

    def test_a_verified_request_is_never_in_the_queue_and_has_no_admin_label(self):
        req = posted_minutes_ago(make_request(self.owner, self.location, hospital=self.hospital), 500)
        self.assertTrue(req.is_visible_to_donors)
        self.assertFalse(req.needs_timeout_review)
        self.assertEqual(req.release_label, "")

    def test_expired_fulfilled_and_blocked_requests_are_not_queued(self):
        expired = self.late()
        BloodRequest.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        fulfilled = self.late()
        BloodRequest.objects.filter(pk=fulfilled.pk).update(status=STATUS_FULFILLED)
        poster = User.objects.create_user(username="blocked_poster")
        blocked = make_request(poster, self.location, hospital=self.hospital, is_verified=False)
        posted_minutes_ago(blocked, 60)
        UserBlock.objects.create(user=poster)
        queued = set(awaiting_timeout_review().values_list("pk", flat=True))
        for req in (expired, fulfilled, blocked):
            self.assertNotIn(req.pk, queued)

    def test_the_queryset_and_the_property_agree_in_every_case(self):
        cases = [self.unverified(), self.late(), make_request(self.owner, self.location, hospital=self.hospital)]
        queued = set(awaiting_timeout_review().values_list("pk", flat=True))
        for req in cases:
            req.refresh_from_db()
            with self.subTest(request=req.pk):
                self.assertEqual(req.needs_timeout_review, req.pk in queued)

    def test_a_late_request_is_not_on_the_public_board(self):
        req = self.late()
        html = self.client.get(reverse("blood_requests:list")).content.decode()
        self.assertNotIn(reverse("blood_requests:detail", args=[req.pk]), html)


@FAST_HASHER
class EscalationTests(Base):
    def setUp(self):
        super().setUp()
        self.admin1 = User.objects.create_user(username="admin1", password="x", is_staff=True)
        self.admin2 = User.objects.create_user(username="admin2", password="x", is_staff=True)

    def test_a_missed_deadline_tells_every_admin_and_the_requester_once(self):
        self.late()
        self.assertEqual(escalate_overdue_requests(), 1)
        self.assertEqual(escalate_overdue_requests(), 0)  # a second poll finds nothing new
        for admin in (self.admin1, self.admin2):
            self.assertEqual(Notification.objects.filter(user=admin, kind=Notification.TIMED_OUT).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.owner, kind=Notification.TIMED_OUT).count(), 1)

    def test_a_request_still_inside_its_deadline_tells_nobody(self):
        self.unverified()
        self.assertEqual(escalate_overdue_requests(), 0)
        self.assertFalse(Notification.objects.exists())

    def test_the_admin_notification_points_at_the_timed_out_queue(self):
        self.late()
        escalate_overdue_requests()
        note = Notification.objects.get(user=self.admin1)
        self.assertIn("state=timeout", note.url)

    def test_polling_the_bell_is_enough_to_escalate(self):
        self.late()
        self.client.force_login(self.admin1)
        self.client.get(reverse("notifications:count"))
        self.assertTrue(Notification.objects.filter(user=self.admin1, kind=Notification.TIMED_OUT).exists())

    def test_the_owner_sees_waiting_for_an_admin_not_released(self):
        req = self.late()
        self.client.force_login(self.owner)
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertIn("an admin will approve or reject it", html)
        self.assertNotIn("released to donors automatically", html)
        self.assertNotIn("Auto-approved", html)


@FAST_HASHER
class AdminDecisionTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.client.force_login(self.admin)
        self.req = self.late()

    def decide(self, decision, note="", req=None):
        req = req or self.req
        return self.client.post(
            reverse("siteadmin:request_timeout", args=[req.pk]), {"decision": decision, "note": note}
        )

    def test_approving_releases_it_labelled_and_never_marks_it_verified(self):
        self.decide("approve", "rang the ward")
        self.req.refresh_from_db()
        self.assertTrue(self.req.is_visible_to_donors)
        self.assertIn(self.req, open_requests())
        self.assertFalse(self.req.is_verified)
        self.assertIsNone(self.req.verified_at)
        self.assertEqual(self.req.release_label, APPROVED)
        self.assertEqual(self.req.timeout_decided_by, self.admin)
        self.assertNotIn(self.req, awaiting_timeout_review())

    def test_approving_restarts_the_closing_time_it_lost_while_hidden(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(expires_at=timezone.now() + timedelta(minutes=5))
        self.decide("approve")
        self.req.refresh_from_db()
        self.assertGreater(self.req.expires_at, timezone.now() + timedelta(hours=20))

    def test_approving_is_written_to_the_audit_log(self):
        self.decide("approve", "checked by phone")
        entry = AdminAction.objects.get()
        self.assertEqual(entry.action, AdminAction.APPROVED_TIMEOUT)
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.note, "checked by phone")

    def test_rejecting_closes_it_for_good(self):
        self.decide("reject", "looks fake")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_REJECTED)
        self.assertEqual(self.req.timeout_review, "rejected")
        self.assertFalse(self.req.is_visible_to_donors)
        self.assertNotIn(self.req, open_requests())
        self.assertNotIn(self.req, awaiting_timeout_review())
        self.assertEqual(AdminAction.objects.get().action, AdminAction.REJECTED_TIMEOUT)

    def test_the_requester_is_told_either_way(self):
        self.decide("approve")
        other = self.late()
        self.decide("reject", "no", req=other)
        kinds = set(Notification.objects.filter(user=self.owner).values_list("kind", flat=True))
        self.assertIn(Notification.ADMIN_APPROVED, kinds)
        self.assertIn(Notification.ADMIN_REJECTED, kinds)

    def test_a_decision_cannot_be_contradicted_by_a_second_one(self):
        self.decide("approve")
        self.decide("reject")
        self.req.refresh_from_db()
        self.assertTrue(self.req.released_early)
        self.assertNotEqual(self.req.status, STATUS_REJECTED)
        self.assertEqual(AdminAction.objects.count(), 1)

    def test_a_request_still_inside_its_deadline_cannot_be_decided(self):
        fresh = self.unverified()
        self.decide("approve", req=fresh)
        fresh.refresh_from_db()
        self.assertFalse(fresh.released_early)
        self.assertFalse(AdminAction.objects.exists())

    def test_an_unknown_decision_changes_nothing(self):
        self.decide("maybe")
        self.req.refresh_from_db()
        self.assertEqual(self.req.timeout_review, "none")

    def test_an_ordinary_user_cannot_decide(self):
        self.client.force_login(self.owner)
        response = self.decide("approve")
        self.assertIn(response.status_code, (302, 403, 404))
        self.req.refresh_from_db()
        self.assertFalse(self.req.released_early)

    def test_a_get_cannot_decide(self):
        response = self.client.get(reverse("siteadmin:request_timeout", args=[self.req.pk]))
        self.assertEqual(response.status_code, 405)

    def test_the_timed_out_tab_lists_it_with_approve_and_reject(self):
        html = self.client.get(reverse("siteadmin:requests") + "?state=timeout").content.decode()
        self.assertIn(self.req.patient_name, html)
        self.assertIn(">Approve<", html)
        self.assertIn(">Reject<", html)

    def test_the_overview_shows_the_waiting_requests(self):
        html = self.client.get(reverse("siteadmin:overview")).content.decode()
        self.assertIn("Hospital missed its deadline", html)

    def test_a_decided_request_leaves_the_tab(self):
        self.decide("approve")
        html = self.client.get(reverse("siteadmin:requests") + "?state=timeout").content.decode()
        self.assertNotIn(reverse("blood_requests:detail", args=[self.req.pk]), html)


@FAST_HASHER
class AdminApprovalLabelTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.client.force_login(self.admin)

    def test_an_approved_after_timeout_request_shows_the_approved_label_never_verified(self):
        req = self.late()
        self.client.post(reverse("siteadmin:request_timeout", args=[req.pk]), {"decision": "approve"})
        self.client.logout()
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertIn(APPROVED, html)
        self.assertNotIn("Verified by hospital", html)

    def test_a_request_held_for_the_unit_review_cannot_be_verified_around_it(self):
        req = self.unverified(units_needed=9, extra_reason="x" * 30)
        self.client.post(reverse("siteadmin:request_verify", args=[req.pk]))
        req.refresh_from_db()
        self.assertFalse(req.is_verified)
        self.assertFalse(req.is_visible_to_donors)


@FAST_HASHER
class HospitalDeskTests(Base):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(username="desk", password="x")
        HospitalAccount.objects.create(user=self.staff, hospital=self.hospital, staff_name="Desk")
        self.client.force_login(self.staff)

    def verify(self, req):
        return self.client.post(reverse("hospitals:verify", args=[req.pk]))

    def test_the_hospital_can_still_verify_late_and_that_leaves_the_queue(self):
        req = self.late()
        self.verify(req)
        req.refresh_from_db()
        self.assertTrue(req.is_verified)
        self.assertEqual(req.verified_by, self.staff)
        self.assertEqual(req.release_label, "")
        self.assertNotIn(req, awaiting_timeout_review())
        self.assertTrue(req.is_visible_to_donors)

    def test_verifying_tells_the_requester(self):
        req = self.unverified()
        self.verify(req)
        self.assertTrue(Notification.objects.filter(user=self.owner, kind=Notification.HOSPITAL_VERIFIED).exists())

    def test_a_rejected_request_cannot_be_verified(self):
        req = self.late()
        BloodRequest.objects.filter(pk=req.pk).update(status=STATUS_REJECTED, timeout_review="rejected")
        self.verify(req)
        req.refresh_from_db()
        self.assertFalse(req.is_verified)

    def test_the_desk_says_deadline_missed_and_no_longer_says_released_automatically(self):
        self.late()
        escalate_overdue_requests()
        html = self.client.get(reverse("hospitals:dashboard")).content.decode()
        self.assertIn("Deadline missed", html)
        self.assertNotIn("released automatically", html)
        self.assertNotIn("auto-approved", html.lower())

    def test_a_new_request_tells_the_hospital_staff(self):
        from blood_requests.services import create_request

        req = BloodRequest(
            patient_name="P", blood_type="O-", units_needed=1, urgency="Normal",
            hospital=self.hospital, contact_phone="03001234567",
        )
        create_request(self.owner, req)
        self.assertTrue(
            Notification.objects.filter(user=self.staff, kind=Notification.REQUEST_FOR_HOSPITAL).exists()
        )
