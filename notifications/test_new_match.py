"""Donors are told about a request the moment donors can see it, once."""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from datetime import timedelta
from io import StringIO

from accounts.models import UserBlock
from blood_requests.models import BloodRequest
from blood_requests.services import announce_if_visible, escalate_overdue_requests, respond_to_request, verify_by_hospital
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from hospitals.models import HospitalAccount
from notifications.models import Notification
from siteadmin import services as admin_services

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.area2 = make_location("Sukkur", "Barrage Road")
        self.other_city = make_location("Karachi", "Saddar")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner")
        self.boss = User.objects.create_user(username="boss", is_staff=True)
        self.desk = User.objects.create_user(username="desk")
        HospitalAccount.objects.create(user=self.desk, hospital=self.hospital, staff_name="Desk")
        self.req = make_request(self.owner, self.location, hospital=self.hospital,
                                blood_type="A+", urgency="Critical", is_verified=False)

    def donor(self, name, blood_type="O-", location=None, **kw):
        return make_donor(name, blood_type, location or self.location, **kw)

    def told(self):
        return set(Notification.objects.filter(kind=Notification.NEW_MATCH).values_list("user__username", flat=True))


class WhoIsToldTests(Base):
    def setUp(self):
        super().setUp()
        self.good = self.donor("good")
        self.same_city = self.donor("same_city", "A+", self.area2)

    def go_live(self):
        verify_by_hospital(self.desk, self.req.pk)

    def test_compatible_available_rested_donors_in_the_city_are_told(self):
        self.go_live()
        self.assertEqual(self.told(), {"good", "same_city"})

    def test_the_message_names_urgency_blood_type_and_hospital_and_links_to_the_request(self):
        self.go_live()
        note = Notification.objects.get(user__username="good", kind=Notification.NEW_MATCH)
        self.assertIn("Critical", note.message)
        self.assertIn("A+", note.message)
        self.assertIn("Civil Hospital", note.message)
        self.assertEqual(note.url, f"/requests/{self.req.pk}/")

    def test_people_who_could_not_respond_are_not_told(self):
        self.donor("wrong_type", "B+")
        self.donor("unavailable", is_available=False)
        self.donor("resting", days_since_donation=20)
        self.donor("far_away", location=self.other_city)
        blocked = self.donor("blocked")
        UserBlock.objects.create(user=blocked.user)
        self.go_live()
        self.assertEqual(self.told(), {"good", "same_city"})

    def test_the_requester_is_never_told_about_their_own_request(self):
        make_donor("owner_profile", "A+", self.location, user=self.owner)
        self.go_live()
        self.assertNotIn("owner", self.told())

    def test_nothing_is_sent_while_the_request_is_still_hidden(self):
        self.assertEqual(announce_if_visible(self.req.pk), 0)
        self.assertEqual(self.told(), set())

    def test_being_late_alone_tells_nobody(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(days=1))
        escalate_overdue_requests()
        self.assertEqual(self.told(), set())

    def test_nobody_is_told_twice(self):
        self.go_live()
        self.assertEqual(announce_if_visible(self.req.pk), 0)
        self.assertEqual(Notification.objects.filter(kind=Notification.NEW_MATCH).count(), 2)

    def test_a_donor_who_registers_later_is_told_on_the_next_announce_only_once(self):
        self.go_live()
        self.donor("late_joiner")
        self.assertEqual(announce_if_visible(self.req.pk), 1)
        self.assertEqual(announce_if_visible(self.req.pk), 0)

    def test_a_closed_request_tells_nobody(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(is_verified=True, status="Fulfilled")
        self.assertEqual(announce_if_visible(self.req.pk), 0)


class EveryWayOfGoingLive(Base):
    def setUp(self):
        super().setUp()
        self.donor("good")

    def test_an_admin_verification_tells_donors(self):
        admin_services.verify_request(self.boss, self.req)
        self.assertEqual(self.told(), {"good"})

    def test_approving_after_a_timeout_tells_donors_and_rejecting_does_not(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.req.refresh_from_db()
        other = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+", is_verified=False)
        BloodRequest.objects.filter(pk=other.pk).update(created_at=timezone.now() - timedelta(days=1))
        other.refresh_from_db()
        admin_services.review_timeout(self.boss, other, False, "no")
        self.assertEqual(self.told(), set())
        admin_services.review_timeout(self.boss, self.req, True, "ok")
        self.assertEqual(self.told(), {"good"})

    def test_an_over_limit_request_tells_donors_when_the_hospital_verifies_it(self):
        big = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+",
                           is_verified=False, units_needed=9, extra_reason="x" * 30)
        self.assertEqual(self.told(), set())  # hidden until someone accepts it
        verify_by_hospital(self.desk, big.pk)
        self.assertEqual(self.told(), {"good"})

    def test_an_over_limit_request_the_hospital_missed_tells_donors_only_when_the_admin_approves(self):
        big = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+",
                           is_verified=False, units_needed=9, extra_reason="x" * 30)
        BloodRequest.objects.filter(pk=big.pk).update(created_at=timezone.now() - timedelta(days=1))
        big.refresh_from_db()
        self.assertEqual(self.told(), set())
        admin_services.review_extra_units(self.boss, big, True, "fine")
        self.assertEqual(self.told(), {"good"})


class HospitalStaffHearAboutOffers(Base):
    def test_staff_are_told_when_a_donor_offers_but_the_requester_is_not_doubled_up(self):
        self.req.is_verified = True
        self.req.save()
        user = self.donor("helper").user
        respond_to_request(user, self.req.pk)
        self.assertEqual(Notification.objects.filter(user=self.desk, kind=Notification.DONOR_RESPONSE).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.owner, kind=Notification.DONOR_RESPONSE).count(), 1)

    def test_a_staff_member_who_posted_the_request_gets_just_one(self):
        mine = make_request(self.desk, self.location, hospital=self.hospital, blood_type="A+")
        user = self.donor("helper").user
        respond_to_request(user, mine.pk)
        self.assertEqual(Notification.objects.filter(user=self.desk, kind=Notification.DONOR_RESPONSE).count(), 1)

    def test_other_hospitals_staff_are_not_told(self):
        other = make_hospital("Other Hospital", self.location)
        stranger = User.objects.create_user(username="stranger")
        HospitalAccount.objects.create(user=stranger, hospital=other, staff_name="X")
        self.req.is_verified = True
        self.req.save()
        respond_to_request(self.donor("helper").user, self.req.pk)
        self.assertFalse(Notification.objects.filter(user=stranger).exists())


class EscalateCommandTests(Base):
    def test_the_command_escalates_and_reports(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(days=1))
        out = StringIO()
        call_command("escalate_requests", stdout=out)
        self.assertIn("Escalated 1 request(s).", out.getvalue())
        self.assertTrue(Notification.objects.filter(user=self.boss, kind=Notification.TIMED_OUT).exists())

    def test_running_it_again_does_nothing_new(self):
        BloodRequest.objects.filter(pk=self.req.pk).update(created_at=timezone.now() - timedelta(days=1))
        call_command("escalate_requests", stdout=StringIO())
        out = StringIO()
        call_command("escalate_requests", stdout=out)
        self.assertIn("Escalated 0 request(s).", out.getvalue())
        self.assertEqual(Notification.objects.filter(user=self.boss).count(), 1)
