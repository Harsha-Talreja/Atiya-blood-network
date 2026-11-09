from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from blood_requests.matching import find_matching_donors
from blood_requests.models import BloodRequest, DonorResponse, Report
from core.constants import (
    BLOOD_TYPES, STATUS_EXPIRED, STATUS_FULFILLED, STATUS_PENDING,
    URGENCY_CRITICAL, URGENCY_HOURS, URGENCY_NORMAL, URGENCY_URGENT,
)
from core.models import Location
from donors.models import DonorProfile
from hospitals.models import Hospital

User = get_user_model()


# --- small helpers so each test reads clearly -------------------------------
def make_location(city, area):
    location, _ = Location.objects.get_or_create(city=city, area=area)
    return location


def make_hospital(name, location):
    hospital, _ = Hospital.objects.get_or_create(name=name, location=location)
    return hospital


def make_request(requester, location, blood_type="A+", urgency=URGENCY_NORMAL, hospital=None, **extra):
    data = dict(
        patient_name="Test Patient", units_needed=1,
        contact_phone="03001234567",
        is_verified=True,  # already-approved by default; tests about verification itself override this
    )
    data.update(extra)
    return BloodRequest.objects.create(
        requester=requester, location=location,
        hospital=hospital or make_hospital("Civil Hospital", location),
        blood_type=blood_type, urgency=urgency, **data,
    )


def make_donor(name, blood_type, location, days_since_donation=None,
               is_available=True, user=None):
    last = (
        None if days_since_donation is None
        else timezone.localdate() - timedelta(days=days_since_donation)
    )
    return DonorProfile.objects.create(
        user=user or User.objects.create_user(username=name),  # no password = no slow hashing
        full_name=name, phone="03001234567", blood_type=blood_type,
        location=location, is_available=is_available, last_donation_date=last,
    )


class RequestExpiryTests(TestCase):
    def setUp(self):
        self.requester = User.objects.create_user(username="requester")
        self.location = make_location("Sukkur", "Military Road")

    def test_new_request_defaults(self):
        req = make_request(self.requester, self.location)
        self.assertEqual(req.status, STATUS_PENDING)
        self.assertEqual(req.display_status, STATUS_PENDING)
        self.assertTrue(req.is_open)

    def test_expiry_is_set_from_urgency(self):
        for urgency in (URGENCY_CRITICAL, URGENCY_URGENT, URGENCY_NORMAL):
            with self.subTest(urgency=urgency):
                before = timezone.now()
                req = make_request(self.requester, self.location, urgency=urgency)
                after = timezone.now()
                delta = timedelta(hours=URGENCY_HOURS[urgency])
                self.assertTrue(before + delta <= req.expires_at <= after + delta)

    def test_expiry_hours_are_24_48_72(self):
        self.assertEqual(URGENCY_HOURS[URGENCY_CRITICAL], 24)
        self.assertEqual(URGENCY_HOURS[URGENCY_URGENT], 48)
        self.assertEqual(URGENCY_HOURS[URGENCY_NORMAL], 72)

    def test_explicit_expiry_is_not_overwritten(self):
        past = timezone.now() - timedelta(hours=1)
        req = make_request(self.requester, self.location, expires_at=past)
        self.assertEqual(req.expires_at, past)

    def test_expiry_not_recalculated_on_later_saves(self):
        req = make_request(self.requester, self.location)
        original = req.expires_at
        req.note = "Updated note"
        req.save()
        req.refresh_from_db()
        self.assertEqual(req.expires_at, original)

    def test_pending_request_past_deadline_displays_expired(self):
        req = make_request(
            self.requester, self.location,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(req.status, STATUS_PENDING)          # stored value unchanged
        self.assertEqual(req.display_status, STATUS_EXPIRED)  # shown value
        self.assertFalse(req.is_open)

    def test_fulfilled_request_never_displays_expired(self):
        req = make_request(
            self.requester, self.location, status=STATUS_FULFILLED,
            expires_at=timezone.now() - timedelta(days=5),
        )
        self.assertEqual(req.display_status, STATUS_FULFILLED)
        self.assertFalse(req.is_open)


class DonorResponseTests(TestCase):
    def test_same_donor_cannot_respond_twice_to_one_request(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="r"), location)
        donor = make_donor("Donor One", "O-", location)
        DonorResponse.objects.create(request=req, donor=donor)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():  # keeps the test transaction usable afterwards
                DonorResponse.objects.create(request=req, donor=donor)


class ReportTests(TestCase):
    def test_same_person_cannot_report_the_same_request_twice(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="r"), location)
        reporter = User.objects.create_user(username="reporter")
        Report.objects.create(request=req, reporter=reporter, reason="Fake or hoax")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Report.objects.create(request=req, reporter=reporter, reason="Spam or advertising")

    def test_two_different_people_can_each_report_the_same_request(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="r"), location)
        Report.objects.create(request=req, reporter=User.objects.create_user(username="a"), reason="Fake or hoax")
        Report.objects.create(request=req, reporter=User.objects.create_user(username="b"), reason="Spam or advertising")
        self.assertEqual(req.reports.count(), 2)

    def test_defaults_to_unresolved(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(User.objects.create_user(username="r"), location)
        report = Report.objects.create(
            request=req, reporter=User.objects.create_user(username="reporter"), reason="Fake or hoax",
        )
        self.assertFalse(report.resolved)


class MatchingTests(TestCase):
    """Every test uses an A+ request in Sukkur / Military Road.
    A+ can receive from: A+, A-, O+, O-."""

    def setUp(self):
        self.requester = User.objects.create_user(username="requester")
        self.military = make_location("Sukkur", "Military Road")
        self.barrage = make_location("Sukkur", "Barrage Road")
        self.rohri = make_location("Rohri", "Rohri City")
        self.request = make_request(self.requester, self.military, blood_type="A+")

    def names(self):
        return [d.full_name for d in find_matching_donors(self.request)]

    def test_only_compatible_blood_types_are_returned(self):
        for i, blood_type in enumerate(BLOOD_TYPES):
            make_donor(f"donor_{i}", blood_type, self.military)
        found_types = {d.blood_type for d in find_matching_donors(self.request)}
        self.assertEqual(found_types, {"A+", "A-", "O+", "O-"})

    def test_excludes_unavailable_donors(self):
        make_donor("available", "A+", self.military)
        make_donor("unavailable", "A+", self.military, is_available=False)
        self.assertEqual(self.names(), ["available"])

    def test_excludes_donors_still_in_cooldown(self):
        make_donor("never_donated", "A+", self.military, days_since_donation=None)
        make_donor("day_90", "A+", self.military, days_since_donation=90)
        make_donor("day_89", "A+", self.military, days_since_donation=89)
        make_donor("day_30", "A+", self.military, days_since_donation=30)
        self.assertEqual(set(self.names()), {"never_donated", "day_90"})

    def test_excludes_incompatible_blood_types(self):
        make_donor("compatible", "O-", self.military)
        make_donor("incompatible_b", "B+", self.military)
        make_donor("incompatible_ab", "AB+", self.military)
        self.assertEqual(self.names(), ["compatible"])

    def test_excludes_donors_in_other_cities(self):
        make_donor("same_city", "A+", self.barrage)
        make_donor("other_city", "A+", self.rohri)
        self.assertEqual(self.names(), ["same_city"])

    def test_excludes_the_requesters_own_donor_profile(self):
        make_donor("requester_self", "A+", self.military, user=self.requester)
        make_donor("someone_else", "A+", self.military)
        self.assertEqual(self.names(), ["someone_else"])

    def test_same_area_first_then_longest_since_last_donation(self):
        make_donor("other_area_old", "O-", self.barrage, days_since_donation=200)
        make_donor("same_area_recent", "O+", self.military, days_since_donation=100)
        make_donor("other_area_never", "A-", self.barrage, days_since_donation=None)
        make_donor("same_area_old", "A+", self.military, days_since_donation=400)
        self.assertEqual(
            self.names(),
            ["same_area_old", "same_area_recent",      # same area, longest wait first
             "other_area_never", "other_area_old"],    # other area, never-donated first
        )

    def test_returns_no_donors_when_nobody_matches(self):
        self.assertEqual(self.names(), [])

    def test_uses_a_single_query_even_when_reading_related_fields(self):
        for i in range(5):
            make_donor(f"donor_{i}", "O+", self.military if i % 2 else self.barrage)
        with self.assertNumQueries(1):
            donors = list(find_matching_donors(self.request))
            for donor in donors:  # would trigger extra queries without select_related
                donor.location.area
                donor.user.username
        self.assertEqual(len(donors), 5)
