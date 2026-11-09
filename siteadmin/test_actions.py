"""Each admin action does its work AND leaves a record.

The pairing is the point: an action without an audit entry is the failure these
tests exist to catch, because that is the state in which a request can vanish
and nobody can say who removed it.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserBlock
from blood_requests.models import BloodRequest, Report
from blood_requests.tests import make_hospital, make_location, make_request
from core.constants import URGENCY_CRITICAL
from siteadmin.models import AdminAction

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class ActionTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.staff = User.objects.create_user("boss", password="pw", is_staff=True)
        self.poster = User.objects.create_user("poster", password="pw")
        self.client.force_login(self.staff)

    def unverified(self, **extra):
        return make_request(
            self.poster, self.location, hospital=self.hospital, is_verified=False, **extra
        )

    # ------------------------------------------------------------ verify

    def test_verifying_marks_the_request_and_names_the_admin_who_did_it(self):
        req = self.unverified()
        self.client.post(reverse("siteadmin:request_verify", args=[req.pk]), {"note": "rang the ward"})
        req.refresh_from_db()
        self.assertTrue(req.is_verified)
        self.assertEqual(req.verified_by, self.staff)
        self.assertIsNotNone(req.verified_at)

    def test_verifying_writes_an_audit_entry_with_the_reason(self):
        req = self.unverified()
        self.client.post(reverse("siteadmin:request_verify", args=[req.pk]), {"note": "rang the ward"})
        entry = AdminAction.objects.get()
        self.assertEqual(entry.action, AdminAction.VERIFIED_REQUEST)
        self.assertEqual(entry.actor, self.staff)
        self.assertEqual(entry.actor_name, "boss")
        self.assertIn(str(req.pk), entry.target)
        self.assertEqual(entry.note, "rang the ward")

    # ------------------------------------------------- verified by an admin

    def test_an_admin_verified_request_is_labelled_verified_by_admin_never_by_hospital(self):
        req = self.unverified(urgency=URGENCY_CRITICAL)
        self.client.post(reverse("siteadmin:request_verify", args=[req.pk]))
        req.refresh_from_db()
        self.assertTrue(req.is_visible_to_donors)
        self.assertEqual(req.verified_label, "Verified by admin")
        self.client.logout()
        html = self.client.get(reverse("blood_requests:detail", args=[req.pk])).content.decode()
        self.assertIn("Verified by admin", html)
        self.assertNotIn("Verified by hospital", html)

    def test_a_verified_request_appears_on_the_public_board(self):
        from blood_requests.selectors import open_requests

        req = self.unverified(urgency=URGENCY_CRITICAL)
        self.assertNotIn(req, open_requests())
        self.client.post(reverse("siteadmin:request_verify", args=[req.pk]))
        self.assertIn(req, open_requests())

    def test_the_requests_page_has_a_verify_button_and_no_release_button(self):
        # A request still inside its hospital's wait is not listed for admins at all,
        # so the button is for one that has already gone live without the hospital.
        self.unverified(released_early=True)
        html = self.client.get(reverse("siteadmin:requests")).content.decode()
        self.assertIn(">Verify</button>", html)
        self.assertNotIn("Release now", html)

    # ------------------------------------------------------------- check

    def test_marking_a_request_checked_takes_it_off_the_admin_queue_only(self):
        """It changes nothing for donors - the request was already visible."""
        from blood_requests.selectors import unchecked_requests

        req = self.unverified()
        BloodRequest.objects.filter(pk=req.pk).update(released_early=True)
        req.refresh_from_db()
        self.assertIn(req, unchecked_requests())
        self.assertTrue(req.is_visible_to_donors)

        self.client.post(reverse("siteadmin:request_check", args=[req.pk]))
        req.refresh_from_db()

        self.assertNotIn(req, unchecked_requests())
        self.assertTrue(req.is_visible_to_donors)  # donors see no difference
        self.assertEqual(req.checked_by, self.staff)

    # ------------------------------------------------------------ remove

    def test_removing_a_request_deletes_it_and_the_log_still_describes_it(self):
        """The log stores the target as text precisely so this works: the thing
        the entry points at no longer exists."""
        req = self.unverified()
        pk, name = req.pk, req.patient_name

        self.client.post(reverse("siteadmin:request_remove", args=[pk]), {"note": "confirmed hoax"})

        self.assertFalse(BloodRequest.objects.filter(pk=pk).exists())
        entry = AdminAction.objects.get()
        self.assertEqual(entry.action, AdminAction.REMOVED_REQUEST)
        self.assertIn(name, entry.target)
        self.assertIn(str(pk), entry.target)
        self.assertEqual(entry.note, "confirmed hoax")

    # ------------------------------------------------------------ report

    def test_resolving_a_report_closes_it_and_leaves_the_request_up(self):
        req = self.unverified()
        reporter = User.objects.create_user("donor_14")
        report = Report.objects.create(request=req, reporter=reporter, reason="Fake or hoax")

        self.client.post(reverse("siteadmin:report_resolve", args=[report.pk]))

        report.refresh_from_db()
        self.assertTrue(report.resolved)
        self.assertTrue(BloodRequest.objects.filter(pk=req.pk).exists())
        self.assertEqual(AdminAction.objects.get().action, AdminAction.RESOLVED_REPORT)

    # ------------------------------------------------------------- block

    def test_blocking_a_user_records_how_many_requests_it_pulled_down(self):
        self.unverified()
        self.unverified()
        self.client.post(
            reverse("siteadmin:user_block", args=[self.poster.pk]), {"note": "repeated fakes"}
        )
        entry = AdminAction.objects.get()
        self.assertEqual(entry.action, AdminAction.BLOCKED_USER)
        self.assertIn("poster", entry.target)
        self.assertIn("2 open request", entry.target)

    def test_blocking_twice_does_not_fill_the_log(self):
        url = reverse("siteadmin:user_block", args=[self.poster.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(UserBlock.objects.count(), 1)
        self.assertEqual(AdminAction.objects.filter(action=AdminAction.BLOCKED_USER).count(), 1)

    def test_unblocking_lifts_the_block_and_logs_it_separately(self):
        self.client.post(reverse("siteadmin:user_block", args=[self.poster.pk]))
        self.client.post(reverse("siteadmin:user_unblock", args=[self.poster.pk]))
        self.assertFalse(UserBlock.objects.filter(user=self.poster).exists())
        self.assertEqual(
            list(AdminAction.objects.order_by("pk").values_list("action", flat=True)),
            [AdminAction.BLOCKED_USER, AdminAction.UNBLOCKED_USER],
        )

    def test_a_hospital_account_cannot_be_blocked_from_the_panel(self):
        from hospitals.models import HospitalAccount

        desk = User.objects.create_user("civil_desk", password="pw")
        HospitalAccount.objects.create(user=desk, hospital=self.hospital)
        self.client.post(reverse("siteadmin:user_block", args=[desk.pk]))
        self.assertFalse(UserBlock.objects.exists())

    def test_the_users_page_lists_only_donors_and_patients(self):
        from hospitals.models import HospitalAccount

        desk = User.objects.create_user("civil_desk", password="pw")
        HospitalAccount.objects.create(user=desk, hospital=self.hospital)
        page = self.client.get(reverse("siteadmin:users"))
        self.assertContains(page, "poster")
        self.assertNotContains(page, "civil_desk")
        self.assertNotContains(page, "?q=boss")  # the rail shows the signed-in admin, the table must not

    def test_an_admin_cannot_block_their_own_account(self):
        self.client.post(reverse("siteadmin:user_block", args=[self.staff.pk]))
        self.assertFalse(UserBlock.objects.exists())
        self.assertFalse(AdminAction.objects.exists())

    def test_one_admin_cannot_block_another_from_the_panel(self):
        """Staff logins are changed in Django admin, where it takes more than a
        click. A block button here would be an easy way to lock a colleague out."""
        other = User.objects.create_user("boss2", is_staff=True)
        self.client.post(reverse("siteadmin:user_block", args=[other.pk]))
        self.assertFalse(UserBlock.objects.exists())

    # --------------------------------------------------------- audit log

    def test_the_panel_offers_no_way_to_change_or_delete_a_log_entry(self):
        """A log an admin can edit is not a log. Nothing in siteadmin.urls writes
        to AdminAction except through the actions themselves."""
        from siteadmin import urls as siteadmin_urls

        names = {p.name for p in siteadmin_urls.urlpatterns}
        for forbidden in ("audit_delete", "audit_edit", "audit_clear"):
            self.assertNotIn(forbidden, names)

    def test_removing_an_admin_account_keeps_their_entries_readable(self):
        req = self.unverified()
        self.client.post(reverse("siteadmin:request_verify", args=[req.pk]))
        self.staff.delete()
        entry = AdminAction.objects.get()
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.actor_name, "boss")  # the name is copied, not looked up
