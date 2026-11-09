"""A person or request that has just arrived must be the first row, not the last."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.tests import make_donor, make_hospital, make_location, make_request

User = get_user_model()


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class NewestFirst(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="boss", password="x", is_staff=True)
        self.client.force_login(self.staff)
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)

    def names_in_order(self, url_name, names):
        html = self.client.get(reverse(url_name)).content.decode()
        return sorted(names, key=html.index)

    def test_the_newest_account_is_the_first_user_row(self):
        old = User.objects.create_user(username="aaa_old")
        new = User.objects.create_user(username="zzz_new")
        User.objects.filter(pk=old.pk).update(date_joined=timezone.now() - timedelta(days=5))
        self.assertEqual(self.names_in_order("siteadmin:users", ["aaa_old", "zzz_new"]), ["zzz_new", "aaa_old"])

    def test_the_newest_request_is_the_first_request_row(self):
        owner = User.objects.create_user(username="owner")
        first = make_request(owner, self.location, hospital=self.hospital, patient_name="Oldest Patient")
        make_request(owner, self.location, hospital=self.hospital, patient_name="Newest Patient")
        BloodRequest.objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(days=2))
        self.assertEqual(
            self.names_in_order("siteadmin:requests", ["Oldest Patient", "Newest Patient"]),
            ["Newest Patient", "Oldest Patient"],
        )

    def test_the_newest_donor_is_the_first_donor_row(self):
        make_donor("Aaa Early", "O+", self.location)
        make_donor("Zzz Latest", "O+", self.location)
        self.assertEqual(
            self.names_in_order("siteadmin:donors", ["Aaa Early", "Zzz Latest"]), ["Zzz Latest", "Aaa Early"]
        )


class NewestFirstQueues(TestCase):
    """The waiting lists and the donor search also put what just arrived first."""

    def setUp(self):
        self.location = make_location("Sukkur", "Military Road")
        self.hospital = make_hospital("Civil Hospital", self.location)
        self.owner = User.objects.create_user(username="owner")

    def test_extra_unit_requests_waiting_for_an_admin_list_the_newest_first(self):
        from blood_requests.selectors import awaiting_extra_review

        older = make_request(self.owner, self.location, hospital=self.hospital, units_needed=9,
                             extra_reason="x" * 30, is_verified=False)
        newer = make_request(self.owner, self.location, hospital=self.hospital, units_needed=9,
                             extra_reason="x" * 30, is_verified=False)
        BloodRequest.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=2))
        BloodRequest.objects.filter(pk=newer.pk).update(created_at=timezone.now() - timedelta(days=1))
        self.assertEqual(list(awaiting_extra_review().values_list("pk", flat=True)), [newer.pk, older.pk])

    def test_donor_search_lists_the_newest_donor_first(self):
        from donors.selectors import search_donors

        first = make_donor("Aaa Early", "O+", self.location)
        second = make_donor("Zzz Latest", "O+", self.location)
        self.assertEqual([d.pk for d in search_donors()], [second.pk, first.pk])
