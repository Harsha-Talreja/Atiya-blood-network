"""The progress timeline on a request's page.

The rule being protected here is that the timeline never overstates what
happened. In particular: a request released automatically must not be
described as hospital-verified, and a request that closed before anyone saw it
must not look like it is still waiting for a donor.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.tests import make_hospital, make_location, make_request
from blood_requests.tracking import tracking_steps
from core.constants import STATUS_FULFILLED

User = get_user_model()


def posted_minutes_ago(request_obj, minutes):
    """created_at is auto_now_add, so it is moved with an UPDATE."""
    BloodRequest.objects.filter(pk=request_obj.pk).update(
        created_at=timezone.now() - timedelta(minutes=minutes)
    )
    request_obj.refresh_from_db()
    return request_obj


class TrackingStepTests(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner")

    def steps(self, req, responses=0):
        return {s["key"]: s for s in tracking_steps(req, responses)}

    def test_there_are_always_four_stages_in_order(self):
        req = make_request(self.owner, self.location, hospital=self.hospital)
        keys = [s["key"] for s in tracking_steps(req)]
        self.assertEqual(keys, ["posted", "visible", "offered", "closed"])

    def test_a_fresh_request_waits_on_the_hospital(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        steps = self.steps(req)
        self.assertEqual(steps["visible"]["state"], "active")
        self.assertIn(self.hospital.name, steps["visible"]["detail"])
        # Nothing further can be happening yet.
        self.assertEqual(steps["offered"]["state"], "upcoming")
        self.assertEqual(steps["closed"]["state"], "upcoming")

    def test_exactly_one_stage_is_active_while_open(self):
        for verified in (True, False):
            with self.subTest(verified=verified):
                req = make_request(self.owner, self.location, hospital=self.hospital,
                                   is_verified=verified)
                active = [s for s in tracking_steps(req) if s["state"] == "active"]
                self.assertEqual(len(active), 1, active)

    def test_a_verified_request_says_verified_and_names_the_hospital(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=True)
        step = self.steps(req)["visible"]
        self.assertEqual(step["state"], "done")
        self.assertIn("Verified", step["title"])
        self.assertIn(self.hospital.name, step["detail"])

    def test_a_late_request_waits_for_an_admin_and_is_never_called_verified(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        req = posted_minutes_ago(req, 120)
        self.assertFalse(req.is_visible_to_donors)  # lateness alone never releases it

        step = self.steps(req)["visible"]
        self.assertEqual(step["state"], "active")
        self.assertEqual(step["title"], "Waiting for an admin")
        self.assertNotIn("Verified", step["title"])

    def test_an_admin_release_is_its_own_reason(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        req.released_early = True
        req.released_at = timezone.now()
        req.save(update_fields=["released_early", "released_at"])

        step = self.steps(req)["visible"]
        self.assertEqual(step["state"], "done")
        self.assertIn("admin", step["title"].lower())
        self.assertNotIn("Verified", step["title"])

    def test_offers_are_counted_and_worded_for_one(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=True)
        one = self.steps(req, 1)["offered"]
        self.assertEqual(one["state"], "done")
        self.assertIn("1 donor said", one["detail"])

        many = self.steps(req, 3)["offered"]
        self.assertIn("3 donors said", many["detail"])

    def test_a_fulfilled_request_has_nothing_still_happening(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=True)
        req.status = STATUS_FULFILLED
        req.fulfilled_at = timezone.now()
        req.save(update_fields=["status", "fulfilled_at"])

        steps = tracking_steps(req, 1)
        self.assertEqual([s for s in steps if s["state"] == "active"], [])
        self.assertEqual(steps[-1]["title"], "Marked fulfilled")
        self.assertEqual(steps[-1]["state"], "done")

    def test_a_request_that_expired_unverified_says_donors_never_saw_it(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        BloodRequest.objects.filter(pk=req.pk).update(expires_at=timezone.now() - timedelta(hours=1))
        req.refresh_from_db()
        self.assertTrue(req.is_expired)

        steps = self.steps(req)
        self.assertEqual(steps["visible"]["title"], "Never reached donors")
        # It is not still "waiting" for anything: it has stopped.
        self.assertEqual([s for s in tracking_steps(req) if s["state"] == "active"], [])
        self.assertEqual(steps["closed"]["title"], "Expired")


class TrackingOnThePageTests(TestCase):
    """The timeline must render for a visitor who is not signed in."""

    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner")
        self.req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=True)

    def test_the_timeline_is_on_the_detail_page_for_anyone(self):
        response = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tl-step")
        self.assertEqual(response.content.decode().count('class="tl-step'), 4)

    def test_the_count_of_offers_is_shown_but_not_who_they_are(self):
        response = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        # A signed-out visitor never sees the donor list card.
        self.assertNotContains(response, "Donors who offered")
        self.assertIn("response_count", response.context)
