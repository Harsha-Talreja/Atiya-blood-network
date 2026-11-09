"""The two limits on posting a request: three a day, and a standard number of
units per request with a reviewed exception above it.

These check the rules at the points that matter - the backend and the donor
board - not just the wording on the page.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.forms import BloodRequestForm
from blood_requests.models import BloodRequest
from blood_requests.selectors import open_requests
from blood_requests.services import (
    DailyLimitReached,
    create_request,
    daily_limit_message,
    requests_left_today,
    requests_posted_today,
)
from blood_requests.test_views import request_form_data
from blood_requests.tests import make_hospital, make_location, make_request
from core.constants import (
    EXTRA_APPROVED,
    EXTRA_NONE,
    EXTRA_PENDING,
    EXTRA_REJECTED,
    STATUS_REJECTED,
)
from hospitals.models import HospitalAccount
from siteadmin.models import SiteSetting

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])

LIMIT_TEXT = "You have reached your daily limit of 3 blood requests. Please try again tomorrow."
REASON = "Patient is going into open-heart surgery and the surgeon has asked for six units."


class Base(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.user = User.objects.create_user("requester", password="pw")
        self.client.force_login(self.user)

    def post(self, **overrides):
        return self.client.post(
            reverse("blood_requests:new"), request_form_data(self.hospital, **overrides), follow=True
        )


@FAST_HASHER
class DailyLimitTests(Base):
    def test_the_message_is_the_one_that_was_asked_for(self):
        self.assertEqual(daily_limit_message(), LIMIT_TEXT)

    def test_three_requests_go_through_and_the_fourth_is_refused(self):
        for _ in range(3):
            self.assertEqual(self.post().status_code, 200)
        self.assertEqual(BloodRequest.objects.filter(requester=self.user).count(), 3)
        response = self.post()
        self.assertContains(response, LIMIT_TEXT)
        self.assertEqual(BloodRequest.objects.filter(requester=self.user).count(), 3)

    def test_the_backend_refuses_even_if_the_form_page_was_opened_earlier(self):
        """The check is on the POST, not just on opening the form."""
        self.client.get(reverse("blood_requests:new"))  # form open, 3 left
        for _ in range(3):
            make_request(self.user, self.location, hospital=self.hospital)
        self.post()
        self.assertEqual(BloodRequest.objects.filter(requester=self.user).count(), 3)

    def test_create_request_itself_enforces_the_limit(self):
        for _ in range(3):
            make_request(self.user, self.location, hospital=self.hospital)
        draft = BloodRequest(
            patient_name="X", blood_type="A+", units_needed=1, hospital=self.hospital,
            contact_phone="03001234567",
        )
        with self.assertRaises(DailyLimitReached):
            create_request(self.user, draft)

    def test_rejected_and_fulfilled_and_pending_requests_all_count(self):
        make_request(self.user, self.location, hospital=self.hospital, status=STATUS_REJECTED)
        make_request(self.user, self.location, hospital=self.hospital, status="Fulfilled")
        make_request(self.user, self.location, hospital=self.hospital, is_verified=False)
        self.assertEqual(requests_posted_today(self.user), 3)
        self.assertEqual(requests_left_today(self.user), 0)

    def test_a_form_that_fails_validation_is_not_counted(self):
        self.post(patient_name="")
        self.post(contact_phone="nope")
        self.assertEqual(requests_posted_today(self.user), 0)
        self.assertEqual(requests_left_today(self.user), 3)

    def test_yesterdays_requests_do_not_count_after_midnight(self):
        for _ in range(3):
            req = make_request(self.user, self.location, hospital=self.hospital)
            BloodRequest.objects.filter(pk=req.pk).update(
                created_at=timezone.now() - timedelta(days=1, minutes=1)
            )
        self.assertEqual(requests_posted_today(self.user), 0)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(requests_posted_today(self.user), 1)

    def test_someone_elses_requests_do_not_use_up_my_allowance(self):
        other = User.objects.create_user("other", password="pw")
        for _ in range(3):
            make_request(other, self.location, hospital=self.hospital)
        self.assertEqual(requests_left_today(self.user), 3)

    def test_the_form_page_says_how_many_are_left(self):
        self.assertContains(self.client.get(reverse("blood_requests:new")), "3 of 3 requests remaining today")
        make_request(self.user, self.location, hospital=self.hospital)
        self.assertContains(self.client.get(reverse("blood_requests:new")), "2 of 3 requests remaining today")

    def test_my_requests_and_the_dashboard_say_it_too(self):
        make_request(self.user, self.location, hospital=self.hospital)
        self.assertContains(self.client.get(reverse("blood_requests:mine")), "2 of 3 requests remaining today")
        self.assertContains(self.client.get(reverse("core:dashboard")), "2 of 3 left today")


@FAST_HASHER
class UnitLimitTests(Base):
    def test_four_units_need_no_reason_and_are_not_held(self):
        self.post(units_needed="4")
        req = BloodRequest.objects.get()
        self.assertEqual(req.extra_review, EXTRA_NONE)

    def test_five_units_without_a_reason_is_refused(self):
        response = self.post(units_needed="5")
        self.assertFalse(BloodRequest.objects.exists())
        self.assertContains(response, "Please explain why this much blood is needed")

    def test_a_one_word_reason_is_not_enough(self):
        self.post(units_needed="5", extra_reason="urgent")
        self.assertFalse(BloodRequest.objects.exists())

    def test_five_units_with_a_reason_is_saved_and_held_for_an_admin(self):
        self.post(units_needed="5", extra_reason=REASON)
        req = BloodRequest.objects.get()
        self.assertEqual(req.extra_review, EXTRA_PENDING)
        self.assertEqual(req.extra_reason, REASON)

    def test_a_reason_is_optional_inside_the_limit_and_kept_when_given(self):
        self.post(units_needed="2", extra_reason="Thalassemia patient, monthly transfusion.")
        req = BloodRequest.objects.get()
        self.assertEqual(req.extra_review, EXTRA_NONE)
        self.assertIn("Thalassemia", req.extra_reason)

    def test_the_limit_is_a_setting(self):
        row = SiteSetting.load()
        row.max_units_per_request = 6
        row.save()
        self.post(units_needed="6")
        self.assertEqual(BloodRequest.objects.get().extra_review, EXTRA_NONE)
        self.post(units_needed="7")  # no reason
        self.assertEqual(BloodRequest.objects.count(), 1)
        self.assertEqual(BloodRequest.objects.count(), 1)

    def test_lowering_the_limit_applies_to_the_next_request(self):
        row = SiteSetting.load()
        row.max_units_per_request = 2
        row.save()
        self.post(units_needed="3", extra_reason=REASON)
        self.assertEqual(BloodRequest.objects.get().extra_review, EXTRA_PENDING)

    def test_the_form_tells_the_user_the_current_limit(self):
        row = SiteSetting.load()
        row.max_units_per_request = 5
        row.save()
        page = self.client.get(reverse("blood_requests:new"))
        # The limit is in the page for the box to use once someone goes above it; no hint line says it.
        self.assertContains(page, 'data-unit-limit="5"')
        self.assertNotContains(page, "Up to 5 units go out normally")
        self.assertContains(page, "Why is extra blood needed?")

    def test_one_request_cannot_ask_for_more_than_the_hard_cap(self):
        self.post(units_needed="21", extra_reason=REASON)
        self.assertFalse(BloodRequest.objects.exists())

    def test_creating_an_over_limit_request_any_other_way_is_still_held(self):
        """The hold is applied when the row is first saved, not by the form."""
        req = make_request(self.user, self.location, hospital=self.hospital, units_needed=9)
        self.assertEqual(req.extra_review, EXTRA_PENDING)

    def test_the_form_keeps_the_extra_reason_field_optional_in_html(self):
        form = BloodRequestForm()
        self.assertFalse(form.fields["extra_reason"].required)


@FAST_HASHER
class OverLimitIsNeverAutomatic(Base):
    def over_limit(self, **extra):
        return make_request(
            self.user, self.location, hospital=self.hospital, units_needed=6,
            extra_reason=REASON, is_verified=False, **extra,
        )

    def test_waiting_does_not_release_it(self):
        req = self.over_limit()
        BloodRequest.objects.filter(pk=req.pk).update(created_at=timezone.now() - timedelta(days=1))
        req.refresh_from_db()
        self.assertNotIn(req, open_requests())
        self.assertFalse(req.is_visible_to_donors)
        self.assertFalse(req.needs_timeout_review)  # held for the unit review, not the deadline

    def test_the_hospital_verifying_it_does_not_release_it_either(self):
        req = self.over_limit()
        BloodRequest.objects.filter(pk=req.pk).update(is_verified=True)
        req.refresh_from_db()
        self.assertNotIn(req, open_requests())
        self.assertFalse(req.is_visible_to_donors)

    def test_an_admin_releasing_it_early_does_not_bypass_the_review(self):
        req = self.over_limit()
        BloodRequest.objects.filter(pk=req.pk).update(released_early=True)
        req.refresh_from_db()
        self.assertNotIn(req, open_requests())

    def test_it_is_not_on_the_public_board_or_open_to_strangers(self):
        req = self.over_limit()
        self.client.logout()
        self.assertEqual(self.client.get(reverse("blood_requests:detail", args=[req.pk])).status_code, 404)
        stranger = User.objects.create_user("stranger", password="pw")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("blood_requests:detail", args=[req.pk])).status_code, 404)

    def test_the_requester_and_staff_and_that_hospitals_desk_can_read_the_reason(self):
        req = self.over_limit()
        url = reverse("blood_requests:detail", args=[req.pk])
        self.assertContains(self.client.get(url), REASON)

        staff = User.objects.create_user("boss", password="pw", is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(url), REASON)

        desk = User.objects.create_user("civil_desk", password="pw")
        HospitalAccount.objects.create(user=desk, hospital=self.hospital, staff_name="Desk")
        self.client.force_login(desk)
        self.assertContains(self.client.get(url), REASON)

    def test_another_hospitals_desk_cannot(self):
        req = self.over_limit()
        other_hospital = make_hospital("Other Hospital", self.location)
        desk = User.objects.create_user("other_desk", password="pw")
        HospitalAccount.objects.create(user=desk, hospital=other_hospital, staff_name="Desk")
        self.client.force_login(desk)
        self.assertEqual(self.client.get(reverse("blood_requests:detail", args=[req.pk])).status_code, 404)

    def test_the_hospital_desk_shows_the_reason(self):
        self.over_limit()
        desk = User.objects.create_user("civil_desk", password="pw")
        HospitalAccount.objects.create(user=desk, hospital=self.hospital, staff_name="Desk")
        self.client.force_login(desk)
        page = self.client.get(reverse("hospitals:dashboard"))
        self.assertContains(page, REASON)
        self.assertContains(page, "also accepts the extra units")

    def test_a_donor_cannot_respond_to_it(self):
        from blood_requests.models import DonorResponse
        from blood_requests.tests import make_donor

        req = self.over_limit()
        BloodRequest.objects.filter(pk=req.pk).update(is_verified=True)
        donor_user = User.objects.create_user("helper", password="pw")
        make_donor("Helper", "O-", self.location, user=donor_user)
        self.client.force_login(donor_user)
        self.client.post(reverse("blood_requests:respond", args=[req.pk]))
        self.assertFalse(DonorResponse.objects.exists())
