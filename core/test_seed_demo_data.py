"""Tests for the seed_demo_data management command."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from blood_requests.models import BloodRequest
from core.management.commands.seed_demo_data import (
    ADMIN_USERNAME, DEMO_REQUESTER_USERNAME, DONOR_COUNT, DONOR_USERNAMES,
)
from donors.models import DonorProfile
from hospitals.models import Hospital, HospitalAccount

User = get_user_model()

# Real password hashing is deliberately slow, and this command creates 32+ users
# per run; use a fast hasher so this file doesn't dominate the test suite's runtime.
FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def run_seed(*args):
    out = StringIO()
    call_command("seed_demo_data", *args, stdout=out)
    return out.getvalue()


@FAST_HASHER
class SeedDemoDataTests(TestCase):
    def test_does_not_crash_if_a_hospital_name_is_not_globally_unique(self):
        # Hospital.name is only unique per-location (branches are allowed), so a
        # second "Civil Hospital" at a different address is valid data - the seed
        # command must not assume get(name=...) returns exactly one row.
        from blood_requests.tests import make_hospital, make_location
        make_hospital("Civil Hospital", make_location("Sukkur", "Old Sukkur"))
        run_seed()  # must not raise Hospital.MultipleObjectsReturned
        self.assertGreater(BloodRequest.objects.count(), 0)

    def test_creates_the_expected_number_of_accounts_donors_and_requests(self):
        run_seed()
        self.assertTrue(User.objects.filter(username=ADMIN_USERNAME, is_superuser=True).exists())
        self.assertTrue(User.objects.filter(username=DEMO_REQUESTER_USERNAME).exists())
        self.assertEqual(User.objects.filter(username__in=DONOR_USERNAMES).count(), DONOR_COUNT)
        self.assertEqual(DonorProfile.objects.filter(user__username__in=DONOR_USERNAMES).count(), DONOR_COUNT)
        self.assertGreaterEqual(BloodRequest.objects.count(), 10)

    def test_does_not_create_or_touch_any_hospital_accounts(self):
        # Hospital logins are permanent (hospitals/migrations/0003), not demo
        # data - this command must not add, remove, or otherwise touch them.
        before = set(HospitalAccount.objects.values_list("pk", flat=True))
        run_seed()
        after = set(HospitalAccount.objects.values_list("pk", flat=True))
        self.assertEqual(before, after)

    def test_some_seeded_requests_are_left_unverified_for_an_existing_hospital_account(self):
        run_seed()
        unverified = BloodRequest.objects.filter(is_verified=False, status="Pending")
        self.assertGreater(unverified.count(), 0)
        for req in unverified:
            self.assertTrue(
                HospitalAccount.objects.filter(hospital=req.hospital).exists(),
                f"{req.hospital} has an unverified request but no login account to verify it with",
            )

    def test_covers_every_request_status_and_several_urgencies(self):
        run_seed()
        statuses = set(BloodRequest.objects.values_list("status", flat=True))
        self.assertIn("Pending", statuses)
        self.assertIn("Fulfilled", statuses)
        self.assertTrue(any(req.display_status == "Expired" for req in BloodRequest.objects.all()))
        urgencies = set(BloodRequest.objects.values_list("urgency", flat=True))
        self.assertEqual(urgencies, {"Critical", "Urgent", "Normal"})

    def test_includes_both_verified_and_unverified_requests(self):
        run_seed()
        self.assertTrue(BloodRequest.objects.filter(is_verified=True).exists())
        self.assertTrue(BloodRequest.objects.filter(is_verified=False).exists())

    def test_donors_span_more_than_one_blood_type_and_city(self):
        run_seed()
        blood_types = set(DonorProfile.objects.values_list("blood_type", flat=True))
        cities = set(DonorProfile.objects.values_list("location__city", flat=True))
        self.assertGreater(len(blood_types), 1)
        self.assertGreater(len(cities), 1)

    def test_running_twice_without_reset_does_not_duplicate_data(self):
        run_seed()
        first_donor_count = DonorProfile.objects.count()
        first_request_count = BloodRequest.objects.count()
        output = run_seed()
        self.assertIn("already exists", output)
        self.assertEqual(DonorProfile.objects.count(), first_donor_count)
        self.assertEqual(BloodRequest.objects.count(), first_request_count)

    def test_reset_recreates_data_without_duplicating(self):
        run_seed()
        first_donor_count = DonorProfile.objects.count()
        hospital_account_count = HospitalAccount.objects.count()
        run_seed("--reset")
        self.assertEqual(DonorProfile.objects.count(), first_donor_count)
        self.assertEqual(User.objects.filter(username__in=DONOR_USERNAMES).count(), DONOR_COUNT)
        self.assertEqual(HospitalAccount.objects.count(), hospital_account_count)  # untouched by reset

    def test_reset_never_touches_accounts_outside_the_demo_set(self):
        real_admin = User.objects.create_superuser("admin", "a@example.com", "x")
        real_person = User.objects.create_user("harsha", "h@example.com", "x")
        run_seed()
        run_seed("--reset")
        self.assertTrue(User.objects.filter(pk=real_admin.pk).exists())
        self.assertTrue(User.objects.filter(pk=real_person.pk).exists())

    def test_reset_never_touches_the_fixed_hospital_list_itself(self):
        hospital_count_before = Hospital.objects.count()
        run_seed()
        run_seed("--reset")
        self.assertEqual(Hospital.objects.count(), hospital_count_before)

    def test_seeded_phone_numbers_pass_the_projects_own_validator(self):
        from core.validators import phone_validator
        run_seed()
        for donor in DonorProfile.objects.filter(user__username__in=DONOR_USERNAMES):
            phone_validator(donor.phone)  # must not raise

    def test_fails_with_a_clear_message_if_migrations_have_not_seeded_hospitals(self):
        Hospital.objects.all().delete()
        with self.assertRaises(CommandError):
            run_seed()
