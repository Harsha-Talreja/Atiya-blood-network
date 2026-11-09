from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.services import create_request
from blood_requests.tests import make_donor, make_hospital, make_location, make_request
from hospitals.models import HospitalAccount
from notifications import services
from notifications.models import Notification
from siteadmin import services as admin_services

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


class ServiceTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice")
        self.bob = User.objects.create_user(username="bob")

    def test_a_new_notification_is_unread_and_counted(self):
        note = services.notify(self.alice, Notification.DONOR_RESPONSE, "hello")
        self.assertFalse(note.is_read)
        self.assertEqual(services.unread_count(self.alice), 1)
        self.assertEqual(services.unread_count(self.bob), 0)

    def test_marking_read_lowers_the_count_and_is_idempotent(self):
        note = services.notify(self.alice, Notification.DONOR_RESPONSE, "hello")
        services.mark_read(self.alice, note.pk)
        first = Notification.objects.get(pk=note.pk).read_at
        services.mark_read(self.alice, note.pk)
        self.assertEqual(Notification.objects.get(pk=note.pk).read_at, first)
        self.assertEqual(services.unread_count(self.alice), 0)

    def test_nobody_can_mark_another_persons_notification(self):
        note = services.notify(self.alice, Notification.DONOR_RESPONSE, "hello")
        self.assertIsNone(services.mark_read(self.bob, note.pk))
        self.assertEqual(services.unread_count(self.alice), 1)

    def test_mark_all_read_only_touches_that_person(self):
        services.notify(self.alice, Notification.DONOR_RESPONSE, "a1")
        services.notify(self.alice, Notification.DONOR_RESPONSE, "a2")
        services.notify(self.bob, Notification.DONOR_RESPONSE, "b1")
        services.mark_all_read(self.alice)
        self.assertEqual(services.unread_count(self.alice), 0)
        self.assertEqual(services.unread_count(self.bob), 1)

    def test_an_anonymous_user_has_zero(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(services.unread_count(AnonymousUser()), 0)

    def test_notify_many_writes_one_row_per_distinct_person(self):
        services.notify_many([self.alice, self.alice, self.bob, None], Notification.TIMED_OUT, "late")
        self.assertEqual(Notification.objects.count(), 2)

    def test_a_long_message_is_cut_not_rejected(self):
        note = services.notify(self.alice, Notification.TIMED_OUT, "x" * 500)
        self.assertEqual(len(note.message), 240)

    def test_only_active_staff_count_as_admins(self):
        boss = User.objects.create_user(username="boss", is_staff=True)
        User.objects.create_user(username="gone", is_staff=True, is_active=False)
        self.assertEqual(list(services.admins()), [boss])

    def test_removing_a_request_keeps_what_people_were_told(self):
        location = make_location("Sukkur", "Military Road")
        req = make_request(self.alice, location)
        services.notify(self.alice, Notification.DONOR_RESPONSE, "hello", req)
        req.delete()
        note = Notification.objects.get()
        self.assertIsNone(note.request)


@FAST_HASHER
class PageTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="x")
        self.bob = User.objects.create_user(username="bob", password="x")
        self.location = make_location("Sukkur", "Military Road")
        self.req = make_request(self.alice, self.location)
        self.note = services.notify(self.alice, Notification.DONOR_RESPONSE, "A donor offered", self.req)

    def test_every_page_needs_a_login(self):
        for name, args in [("notifications:inbox", []), ("notifications:count", []),
                           ("notifications:read_all", []), ("notifications:read", [self.note.pk])]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 302)
                self.assertIn("login", response["Location"])

    def test_marking_needs_a_post(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("notifications:read", args=[self.note.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("notifications:read_all")).status_code, 405)

    def test_the_inbox_lists_my_notifications_and_not_other_peoples(self):
        services.notify(self.bob, Notification.DONOR_RESPONSE, "secret for bob")
        self.client.force_login(self.alice)
        html = self.client.get(reverse("notifications:inbox")).content.decode()
        self.assertIn("A donor offered", html)
        self.assertNotIn("secret for bob", html)

    def test_the_count_endpoint_returns_the_unread_number(self):
        self.client.force_login(self.alice)
        data = self.client.get(reverse("notifications:count")).json()
        self.assertEqual(data["unread"], 1)
        self.assertEqual(data["latest"], self.note.pk)
        services.notify(self.alice, Notification.DONOR_RESPONSE, "another")
        self.assertEqual(self.client.get(reverse("notifications:count")).json()["unread"], 2)

    def test_the_count_endpoint_is_not_cached(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("notifications:count"))
        self.assertIn("no-cache", response["Cache-Control"])

    def test_the_bell_shows_the_unread_number_on_ordinary_pages(self):
        self.client.force_login(self.alice)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("data-notif-bell", html)
        self.assertIn('data-notif-count>1<', html.replace(" hidden", ""))

    def test_the_bell_is_hidden_when_there_is_nothing_unread(self):
        self.client.force_login(self.bob)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn("data-notif-count hidden", html)

    def test_reading_one_marks_it_and_goes_to_the_request(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("notifications:read", args=[self.note.pk]))
        self.assertRedirects(response, reverse("blood_requests:detail", args=[self.req.pk]),
                             fetch_redirect_response=False)
        self.note.refresh_from_db()
        self.assertTrue(self.note.is_read)

    def test_reading_someone_elses_changes_nothing(self):
        self.client.force_login(self.bob)
        self.client.post(reverse("notifications:read", args=[self.note.pk]))
        self.note.refresh_from_db()
        self.assertFalse(self.note.is_read)

    def test_a_link_pointing_off_site_is_never_followed(self):
        evil = Notification.objects.create(user=self.alice, kind=Notification.TIMED_OUT, message="x",
                                           url="https://evil.example/steal")
        self.client.force_login(self.alice)
        response = self.client.post(reverse("notifications:read", args=[evil.pk]))
        self.assertRedirects(response, reverse("notifications:inbox"), fetch_redirect_response=False)

    def test_mark_all_read_clears_the_badge(self):
        services.notify(self.alice, Notification.DONOR_RESPONSE, "second")
        self.client.force_login(self.alice)
        self.client.post(reverse("notifications:read_all"))
        self.assertEqual(services.unread_count(self.alice), 0)
        self.assertEqual(self.client.get(reverse("notifications:count")).json()["unread"], 0)

    def test_admins_read_theirs_inside_the_panel(self):
        boss = User.objects.create_user(username="boss", password="x", is_staff=True)
        services.notify(boss, Notification.TIMED_OUT, "A hospital was late")
        self.client.force_login(boss)
        self.assertRedirects(self.client.get(reverse("notifications:inbox")),
                             reverse("siteadmin:notifications"), fetch_redirect_response=False)
        html = self.client.get(reverse("siteadmin:notifications")).content.decode()
        self.assertIn("A hospital was late", html)
        self.assertIn("data-notif-bell", html)

    def test_the_admin_page_refuses_ordinary_users(self):
        self.client.force_login(self.alice)
        self.assertNotEqual(self.client.get(reverse("siteadmin:notifications")).status_code, 200)


@FAST_HASHER
class EventTests(TestCase):
    """Each important event leaves a notification for the right person."""

    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.boss = User.objects.create_user(username="boss", password="x", is_staff=True)

    def kinds(self, user):
        return list(Notification.objects.filter(user=user).values_list("kind", flat=True))

    def test_a_donor_response_notifies_the_requester_only(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+")
        user = User.objects.create_user(username="donor", password="x")
        make_donor("Donor", "O-", self.location, user=user)
        self.client.force_login(user)
        self.client.post(reverse("blood_requests:respond", args=[req.pk]))
        self.assertEqual(self.kinds(self.owner), [Notification.DONOR_RESPONSE])
        self.assertEqual(self.kinds(user), [])
        self.assertEqual(self.kinds(self.boss), [])

    def test_a_refused_response_notifies_nobody(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+")
        user = User.objects.create_user(username="donor", password="x")
        make_donor("Donor", "B+", self.location, user=user)
        self.client.force_login(user)
        self.client.post(reverse("blood_requests:respond", args=[req.pk]))
        self.assertFalse(Notification.objects.exists())

    def test_a_hospital_verification_notifies_the_requester(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        desk = User.objects.create_user(username="desk", password="x")
        HospitalAccount.objects.create(user=desk, hospital=self.hospital, staff_name="Desk")
        self.client.force_login(desk)
        self.client.post(reverse("hospitals:verify", args=[req.pk]))
        self.assertIn(Notification.HOSPITAL_VERIFIED, self.kinds(self.owner))

    def test_an_admin_verification_notifies_the_requester(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, is_verified=False)
        admin_services.verify_request(self.boss, req)
        self.assertIn(Notification.HOSPITAL_VERIFIED, self.kinds(self.owner))

    def test_extra_unit_decisions_notify_the_requester(self):
        approved = make_request(self.owner, self.location, hospital=self.hospital,
                                is_verified=False, units_needed=9, extra_reason="x" * 30)
        rejected = make_request(self.owner, self.location, hospital=self.hospital,
                                is_verified=False, units_needed=9, extra_reason="x" * 30)
        admin_services.review_extra_units(self.boss, approved, True, "fine")
        admin_services.review_extra_units(self.boss, rejected, False, "too many")
        kinds = self.kinds(self.owner)
        self.assertIn(Notification.EXTRA_APPROVED, kinds)
        self.assertIn(Notification.EXTRA_REJECTED, kinds)
        note = Notification.objects.get(kind=Notification.EXTRA_REJECTED)
        self.assertIn("too many", note.message)

    def test_an_over_limit_request_tells_every_admin_once_the_hospital_has_missed_its_wait(self):
        from blood_requests.services import escalate_overdue_requests
        second = User.objects.create_user(username="boss2", is_staff=True)
        req = BloodRequest(patient_name="P", blood_type="O-", units_needed=9, urgency="Normal",
                           hospital=self.hospital, contact_phone="03001234567", extra_reason="x" * 30)
        saved = create_request(self.owner, req)
        # Inside the hospital's wait the admins are not bothered.
        self.assertFalse(Notification.objects.filter(kind=Notification.NEEDS_REVIEW).exists())
        BloodRequest.objects.filter(pk=saved.pk).update(created_at=timezone.now() - timedelta(days=1))
        escalate_overdue_requests()
        for admin in (self.boss, second):
            note = Notification.objects.get(user=admin, kind=Notification.NEEDS_REVIEW)
            self.assertIn(reverse("siteadmin:request_review", args=[saved.pk]), note.url)

    def test_a_normal_request_does_not_bother_the_admins(self):
        req = BloodRequest(patient_name="P", blood_type="O-", units_needed=1, urgency="Normal",
                           hospital=self.hospital, contact_phone="03001234567")
        create_request(self.owner, req)
        self.assertFalse(Notification.objects.filter(user=self.boss).exists())

    def test_fulfilling_notifies_the_donors_who_offered(self):
        req = make_request(self.owner, self.location, hospital=self.hospital, blood_type="A+")
        user = User.objects.create_user(username="donor", password="x")
        donor = make_donor("Donor", "O-", self.location, user=user)
        DonorResponse.objects.create(request=req, donor=donor)
        self.client.force_login(self.owner)
        self.client.post(reverse("blood_requests:fulfil", args=[req.pk]))
        self.assertEqual(self.kinds(user), [Notification.FULFILLED])

    def test_unread_count_survives_logout_and_login(self):
        services.notify(self.owner, Notification.DONOR_RESPONSE, "kept")
        self.client.force_login(self.owner)
        self.client.logout()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("notifications:count")).json()["unread"], 1)
