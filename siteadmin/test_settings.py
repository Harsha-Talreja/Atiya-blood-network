"""The waiting times page.

The window is the weak point of auto-approval: at one minute no hospital desk can
answer in time, so almost everything goes out unchecked. Being able to change it
from the panel is what lets a real deployment set a sensible value, so these
tests cover both that it saves and that it actually changes what donors see.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.selectors import awaiting_timeout_review, open_requests
from blood_requests.tests import make_hospital, make_location, make_request
from blood_requests.visibility import wait_minutes, wait_minutes_for
from core.constants import (
    AUTO_APPROVE_MINUTES_BY_URGENCY,
    URGENCY_CRITICAL,
    URGENCY_NORMAL,
    URGENCY_URGENT,
)
from siteadmin.models import AdminAction, SiteSetting

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def posted_minutes_ago(request_obj, minutes):
    BloodRequest.objects.filter(pk=request_obj.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes)
    )
    request_obj.refresh_from_db()
    return request_obj


class SettingsRowTests(TestCase):
    def test_a_fresh_database_behaves_like_the_code_defaults(self):
        """Nothing changes for an existing install until someone edits the page."""
        self.assertEqual(wait_minutes(), AUTO_APPROVE_MINUTES_BY_URGENCY)

    def test_a_second_settings_row_cannot_be_created(self):
        """save() pins the id to 1, so a second row collides instead of quietly
        becoming a shadow copy that nothing reads."""
        from django.db import IntegrityError, transaction

        SiteSetting.load()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SiteSetting.objects.create(critical_wait_minutes=5)
        self.assertEqual(SiteSetting.objects.count(), 1)

    def test_the_settings_row_cannot_be_deleted(self):
        with self.assertRaises(NotImplementedError):
            SiteSetting.load().delete()


@FAST_HASHER
class ChangingTheWaitTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.staff = User.objects.create_user("boss", password="pw", is_staff=True)
        self.poster = User.objects.create_user("poster")
        self.client.force_login(self.staff)

    def save(self, critical=5, urgent=20, normal=60, note=""):
        return self.client.post(
            reverse("siteadmin:settings"),
            {
                "critical_wait_minutes": critical,
                "urgent_wait_minutes": urgent,
                "normal_wait_minutes": normal,
                "note": note,
            },
        )

    def test_saving_stores_all_three_windows(self):
        self.save()
        self.assertEqual(
            wait_minutes(),
            {URGENCY_CRITICAL: 5, URGENCY_URGENT: 20, URGENCY_NORMAL: 60},
        )

    def test_saving_writes_an_audit_entry_that_records_the_old_values(self):
        self.save(note="")
        entry = AdminAction.objects.get()
        self.assertEqual(entry.action, AdminAction.CHANGED_SETTINGS)
        self.assertIn("Critical 5 min", entry.target)
        # With no note of their own, the entry keeps what the values were before.
        self.assertIn("was 1/1/1 min", entry.note)

    def test_a_longer_window_keeps_a_request_hidden_for_longer(self):
        """The change has to reach the board, not just the settings table."""
        self.save(critical=5, urgent=20, normal=60)
        req = make_request(
            self.poster, self.location, hospital=self.hospital,
            urgency=URGENCY_NORMAL, is_verified=False,
        )
        posted_minutes_ago(req, 30)  # past the old 1 minute, inside the new 60

        self.assertFalse(req.needs_timeout_review)
        self.assertNotIn(req, awaiting_timeout_review())

        posted_minutes_ago(req, 61)
        self.assertTrue(req.needs_timeout_review)
        self.assertIn(req, awaiting_timeout_review())
        self.assertNotIn(req, open_requests())  # late is not the same as released

    def test_each_urgency_waits_its_own_length(self):
        self.save(critical=5, urgent=20, normal=60)
        made = {}
        for urgency in (URGENCY_CRITICAL, URGENCY_URGENT, URGENCY_NORMAL):
            req = make_request(
                self.poster, self.location, hospital=self.hospital,
                urgency=urgency, is_verified=False,
            )
            made[urgency] = posted_minutes_ago(req, 10)

        # Ten minutes in: only the Critical one has missed its deadline.
        late = set(awaiting_timeout_review().values_list("pk", flat=True))
        self.assertIn(made[URGENCY_CRITICAL].pk, late)
        self.assertNotIn(made[URGENCY_URGENT].pk, late)
        self.assertNotIn(made[URGENCY_NORMAL].pk, late)

    def test_the_property_and_the_queryset_still_agree_after_a_change(self):
        self.save(critical=5, urgent=20, normal=60)
        for urgency in (URGENCY_CRITICAL, URGENCY_URGENT, URGENCY_NORMAL):
            for age in (1, 10, 30, 90):
                req = make_request(
                    self.poster, self.location, hospital=self.hospital,
                    urgency=urgency, is_verified=False,
                )
                posted_minutes_ago(req, age)
                with self.subTest(urgency=urgency, minutes_old=age):
                    self.assertEqual(
                        req.needs_timeout_review,
                        awaiting_timeout_review().filter(pk=req.pk).exists(),
                        "the model property and the queryset disagree",
                    )

    def test_wait_minutes_for_falls_back_on_an_unknown_urgency(self):
        self.save(critical=5, urgent=20, normal=60)
        self.assertEqual(wait_minutes_for("Nonsense"), 1)

    # ------------------------------------------------------- validation

    def test_critical_cannot_be_made_to_wait_longer_than_normal(self):
        """Almost always a typo, and the kind that costs someone time."""
        response = self.save(critical=60, urgent=20, normal=5)
        self.assertEqual(response.status_code, 200)  # redisplayed, not saved
        self.assertContains(response, "Critical should wait the least")
        self.assertEqual(wait_minutes(), AUTO_APPROVE_MINUTES_BY_URGENCY)

    def test_zero_is_refused(self):
        """A zero wait would switch hospital verification off entirely."""
        self.save(critical=0, urgent=20, normal=60)
        self.assertEqual(wait_minutes()[URGENCY_CRITICAL], 1)

    def test_an_absurdly_long_wait_is_refused(self):
        self.save(critical=5, urgent=20, normal=99999)
        self.assertEqual(wait_minutes()[URGENCY_NORMAL], 1)

    def test_nothing_is_saved_and_nothing_is_logged_when_the_form_is_rejected(self):
        self.save(critical=60, urgent=20, normal=5)
        self.assertFalse(AdminAction.objects.exists())
