"""Marking a request fulfilled puts the donor who helped into their rest period."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import DonorResponse
from blood_requests.services import fulfil_request
from blood_requests.tests import make_donor, make_hospital, make_location, make_request

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FulfilRestsTheDonor(TestCase):
    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.family = User.objects.create_user(username="family", password="x")
        self.req = make_request(self.family, self.location, hospital=self.hospital, blood_type="A+")

    def offer(self, name):
        donor = make_donor(name, "O+", self.location)
        DonorResponse.objects.create(request=self.req, donor=donor)
        return donor

    def test_the_requester_marking_fulfilled_rests_the_donor_automatically(self):
        donor = self.offer("Helper")
        self.client.force_login(self.family)
        self.client.post(reverse("blood_requests:fulfil", args=[self.req.pk]))
        donor.refresh_from_db()
        self.assertEqual(donor.last_donation_date, timezone.localdate())
        self.assertFalse(donor.is_eligible)
        self.assertEqual(donor.days_until_eligible, 90)

    def test_the_donor_is_told_when_they_can_donate_again(self):
        from notifications.models import Notification

        donor = self.offer("Helper")
        fulfil_request(self.req.pk)
        note = Notification.objects.filter(user=donor.user, kind=Notification.FULFILLED).get()
        self.assertIn("Thank you for donating", note.message)
        self.assertIn("resting until", note.message)

    def test_only_as_many_donors_as_units_needed_are_rested(self):
        first = self.offer("First")
        second = self.offer("Second")
        fulfil_request(self.req.pk)  # make_request asks for 1 unit
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertIsNotNone(first.last_donation_date)
        self.assertIsNone(second.last_donation_date)

    def test_an_already_resting_donor_keeps_their_later_date(self):
        donor = self.offer("Helper")
        # Recorded earlier today by the "I donated today" button: unchanged, no error.
        donor.last_donation_date = timezone.localdate()
        donor.save()
        fulfil_request(self.req.pk)
        donor.refresh_from_db()
        self.assertEqual(donor.last_donation_date, timezone.localdate())

    def test_marking_fulfilled_twice_does_not_rest_anyone_again(self):
        donor = self.offer("Helper")
        fulfil_request(self.req.pk)
        DonorResponse.objects.filter(donor=donor).update()
        donor.last_donation_date = timezone.localdate() - timedelta(days=10)
        donor.save()
        self.assertFalse(fulfil_request(self.req.pk))
        donor.refresh_from_db()
        self.assertEqual(donor.last_donation_date, timezone.localdate() - timedelta(days=10))

    def test_a_request_nobody_offered_on_rests_nobody(self):
        bystander = make_donor("Bystander", "O+", self.location)
        staff = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.client.force_login(staff)
        self.client.post(reverse("blood_requests:fulfil", args=[self.req.pk]))
        bystander.refresh_from_db()
        self.assertIsNone(bystander.last_donation_date)
