"""Server-side checks on "I can help", and consistency between statuses.

Every rule is enforced by POSTing straight to the endpoint (as someone bypassing
the page would), not by looking for a hidden button.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserBlock
from blood_requests import services
from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from core.constants import STATUS_FULFILLED, STATUS_PENDING, STATUS_REJECTED
from notifications.models import Notification

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class RespondRules(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+")
        self.user = User.objects.create_user(username="donor", password="x")
        self.donor = make_donor("Donor", "O-", self.location, user=self.user)
        self.client.force_login(self.user)

    def respond(self, req=None):
        req = req or self.req
        return self.client.post(reverse("blood_requests:respond", args=[req.pk]), follow=True)

    def count(self):
        return DonorResponse.objects.count()

    # ------------------------------------------------------------ accepted

    def test_a_compatible_available_rested_donor_is_accepted(self):
        self.respond()
        self.assertEqual(self.count(), 1)

    def test_a_donor_who_never_donated_is_accepted(self):
        self.assertIsNone(self.donor.last_donation_date)
        self.respond()
        self.assertEqual(self.count(), 1)

    def test_a_donor_whose_rest_period_just_ended_is_accepted(self):
        DonorResponse.objects.all().delete()
        self.donor.last_donation_date = timezone.localdate() - timedelta(days=90)
        self.donor.save()
        self.respond()
        self.assertEqual(self.count(), 1)

    def test_accepting_tells_the_requester_and_reminds_the_donor_about_screening(self):
        response = self.respond()
        self.assertTrue(Notification.objects.filter(user=self.owner, kind=Notification.DONOR_RESPONSE).exists())
        self.assertContains(response, "final medical screening")

    # ------------------------------------------------------------ refused

    def test_no_donor_profile_is_refused_and_sent_to_register(self):
        plain = User.objects.create_user(username="plain", password="x")
        self.client.force_login(plain)
        response = self.respond()
        self.assertEqual(self.count(), 0)
        self.assertRedirects(
            self.client.post(reverse("blood_requests:respond", args=[self.req.pk])), reverse("donors:edit")
        )
        self.assertEqual(response.status_code, 200)

    def test_an_incompatible_blood_type_is_refused(self):
        self.donor.blood_type = "B+"  # B+ cannot give to A+
        self.donor.save()
        response = self.respond()
        self.assertEqual(self.count(), 0)
        self.assertContains(response, "given to a A+ patient")

    def test_every_incompatible_pair_is_refused_by_the_backend(self):
        from core.blood import can_donate
        from core.constants import BLOOD_TYPES

        for donor_type in BLOOD_TYPES:
            for patient_type in BLOOD_TYPES:
                if can_donate(donor_type, patient_type):
                    continue
                with self.subTest(donor=donor_type, patient=patient_type):
                    req = make_request(self.owner, self.location, hospital=self.hospital, blood_type=patient_type)
                    self.donor.blood_type = donor_type
                    self.donor.save()
                    self.respond(req)
                    self.assertFalse(DonorResponse.objects.filter(request=req).exists())

    def test_an_unavailable_donor_is_refused(self):
        self.donor.is_available = False
        self.donor.save()
        response = self.respond()
        self.assertEqual(self.count(), 0)
        self.assertContains(response, "marked as unavailable")

    def test_a_donor_still_resting_is_refused(self):
        self.donor.last_donation_date = timezone.localdate() - timedelta(days=30)
        self.donor.save()
        response = self.respond()
        self.assertEqual(self.count(), 0)
        self.assertContains(response, "resting")

    def test_one_day_short_of_the_rest_period_is_refused(self):
        self.donor.last_donation_date = timezone.localdate() - timedelta(days=89)
        self.donor.save()
        self.respond()
        self.assertEqual(self.count(), 0)

    def test_a_request_nobody_has_released_is_refused(self):
        hidden = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+", is_verified=False)
        self.respond(hidden)
        self.assertEqual(self.count(), 0)

    def test_a_request_late_at_its_hospital_is_still_refused(self):
        hidden = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+", is_verified=False)
        BloodRequest.objects.filter(pk=hidden.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.respond(hidden)
        self.assertEqual(self.count(), 0)

    def test_an_expired_request_is_refused(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.respond()
        self.assertEqual(self.count(), 0)
        self.assertContains(response, "expired")

    def test_a_fulfilled_request_is_refused(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(status=STATUS_FULFILLED)
        response = self.respond()
        self.assertEqual(self.count(), 0)
        self.assertContains(response, "already been fulfilled")

    def test_a_rejected_request_is_refused(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(status=STATUS_REJECTED)
        self.respond()
        self.assertEqual(self.count(), 0)

    def test_your_own_request_is_refused(self):
        mine = make_request(self.user, self.location, hospital=self.hospital, blood_type="A+")
        response = self.client.post(reverse("blood_requests:respond", args=[mine.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.count(), 0)

    def test_a_blocked_donor_is_refused(self):
        UserBlock.objects.create(user=self.user)
        self.respond()
        self.assertEqual(self.count(), 0)

    # ---------------------------------------------------------- duplicates

    def test_responding_twice_keeps_one_response_and_one_notification(self):
        self.respond()
        response = self.respond()
        self.assertEqual(self.count(), 1)
        self.assertContains(response, "already offered")
        self.assertEqual(Notification.objects.filter(kind=Notification.DONOR_RESPONSE).count(), 1)

    def test_the_service_names_the_reason_with_a_stable_code(self):
        self.donor.is_available = False
        self.donor.save()
        with self.assertRaises(services.CannotRespond) as caught:
            services.respond_to_request(self.user, self.req.pk)
        self.assertEqual(caught.exception.code, services.UNAVAILABLE)

    # ---------------------------------------------------------------- page

    def test_the_page_offers_the_button_only_to_a_donor_who_would_be_accepted(self):
        html = self.client.get(reverse("blood_requests:detail", args=[self.req.pk])).content.decode()
        self.assertIn("I can help", html)
        # Not available (or resting): the request page is not opened for them at all.
        self.donor.is_available = False
        self.donor.save()
        response = self.client.get(reverse("blood_requests:detail", args=[self.req.pk]))
        self.assertRedirects(response, reverse("donors:profile"), fetch_redirect_response=False)
        # A donor who could normally help, but is already committed elsewhere, is told why.
        self.donor.is_available = True
        self.donor.save()
        other = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+", patient_name="Other One")
        DonorResponse.objects.create(request=other, donor=self.donor)
        html = self.client.get(reverse("blood_requests:detail", args=[self.req.pk])).content.decode()
        self.assertNotIn(">I can help<", html)
        self.assertIn("data-offer-problem", html)

    def test_the_page_tells_an_incompatible_donor_why(self):
        self.donor.blood_type = "AB+"
        self.donor.save()
        html = self.client.get(reverse("blood_requests:detail", args=[self.req.pk])).content.decode()
        self.assertNotIn(">I can help<", html)
        self.assertIn("can&#x27;t be given to", html)


@FAST_HASHER
class StatusConsistency(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+")
        self.user = User.objects.create_user(username="donor", password="x")
        self.donor = make_donor("Donor", "A+", self.location, user=self.user)

    def fulfil(self, as_user=None, offered=True):
        # A requester can only close a request a donor has offered to help with.
        if offered:
            DonorResponse.objects.get_or_create(request=self.req, donor=self.donor)
        self.client.force_login(as_user or self.owner)
        return self.client.post(reverse("blood_requests:fulfil", args=[self.req.pk]), follow=True)

    def test_fulfilling_sets_the_time_once_and_repeating_changes_nothing(self):
        self.fulfil()
        self.req.refresh_from_db()
        first = self.req.fulfilled_at
        self.assertEqual(self.req.status, STATUS_FULFILLED)
        self.fulfil()
        self.req.refresh_from_db()
        self.assertEqual(self.req.fulfilled_at, first)

    def test_a_request_with_no_offer_cannot_be_fulfilled_by_its_owner(self):
        response = self.fulfil(offered=False)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_PENDING)
        self.assertIsNone(self.req.fulfilled_at)
        self.assertContains(response, "A donor needs to offer to help before you can mark this fulfilled.")

    def test_once_a_donor_has_offered_the_owner_can_fulfil(self):
        self.fulfil(offered=False)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_PENDING)
        self.fulfil(offered=True)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_FULFILLED)

    def test_an_admin_can_still_close_a_request_with_no_offers(self):
        admin = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.fulfil(as_user=admin, offered=False)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_FULFILLED)

    def test_a_rejected_request_cannot_be_fulfilled(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(status=STATUS_REJECTED)
        response = self.fulfil()
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_REJECTED)
        self.assertIsNone(self.req.fulfilled_at)
        self.assertContains(response, "rejected request can")

    def test_fulfilling_tells_the_donors_who_offered_exactly_once(self):
        DonorResponse.objects.create(request=self.req, donor=self.donor)
        self.fulfil()
        self.fulfil()
        self.assertEqual(Notification.objects.filter(user=self.user, kind=Notification.FULFILLED).count(), 1)

    def test_nobody_can_respond_after_it_is_fulfilled(self):
        self.fulfil()
        before = DonorResponse.objects.count()
        other = User.objects.create_user(username="late_donor", password="x")
        make_donor("Late Donor", "A+", self.location, user=other)
        self.client.force_login(other)
        self.client.post(reverse("blood_requests:respond", args=[self.req.pk]))
        self.assertEqual(DonorResponse.objects.count(), before)

    def test_a_stranger_cannot_fulfil_someone_elses_request(self):
        response = self.fulfil(as_user=self.user)
        self.assertEqual(response.status_code, 403)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, STATUS_PENDING)

    def test_a_fulfilled_request_stays_fulfilled_when_it_would_also_be_expired(self):
        self.fulfil()
        BloodRequest.objects.filter(pk=self.req.pk).update(expires_at=timezone.now() - timedelta(days=1))
        self.req.refresh_from_db()
        self.assertEqual(self.req.display_status, STATUS_FULFILLED)
        self.assertFalse(self.req.is_open)

    def test_the_hospital_cannot_verify_a_fulfilled_request(self):
        from hospitals.models import HospitalAccount

        staff = User.objects.create_user(username="desk", password="x")
        HospitalAccount.objects.create(user=staff, hospital=self.hospital, staff_name="Desk")
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        BloodRequest.objects.filter(pk=req.pk).update(status=STATUS_FULFILLED)
        self.client.force_login(staff)
        self.client.post(reverse("hospitals:verify", args=[req.pk]))
        req.refresh_from_db()
        self.assertFalse(req.is_verified)

    def test_an_admin_cannot_verify_or_release_a_closed_request(self):
        from siteadmin import services as admin_services

        admin = User.objects.create_user(username="boss", is_staff=True)
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        BloodRequest.objects.filter(pk=req.pk).update(status=STATUS_FULFILLED)
        req.refresh_from_db()
        self.assertFalse(admin_services.verify_request(admin, req))
        req.refresh_from_db()
        self.assertFalse(req.is_verified)


@FAST_HASHER
class OfferedDonorsLeaveTheNearbyList(TestCase):
    """A donor who offered is shown under "Donors who offered" only."""

    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+", is_verified=True)
        self.helper = make_donor("Helper One", "O-", self.location, user=User.objects.create_user(username="helper", password="x"))
        self.waiting = make_donor("Waiting Two", "O-", self.location, user=User.objects.create_user(username="waiting", password="x"))
        self.client.force_login(self.owner)

    def nearby_section(self):
        html = self.client.get(reverse("blood_requests:detail", args=[self.req.pk])).content.decode()
        return html[html.index("rq-ready no-lift"):]

    def test_both_donors_are_nearby_before_anyone_offers(self):
        section = self.nearby_section()
        self.assertIn("Helper One", section)
        self.assertIn("Waiting Two", section)

    def test_a_donor_who_offered_is_no_longer_listed_as_nearby(self):
        DonorResponse.objects.create(request=self.req, donor=self.helper)
        section = self.nearby_section()
        self.assertNotIn("Helper One", section)
        self.assertIn("Waiting Two", section)
