from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from blood_requests.tests import make_location
from hospitals.models import Hospital, HospitalAccount

User = get_user_model()


class HospitalModelTests(TestCase):
    def test_str_includes_the_city(self):
        hospital = Hospital.objects.create(name="Test General Hospital", location=make_location("Sukkur", "Barrage Road"))
        self.assertEqual(str(hospital), "Test General Hospital (Sukkur)")

    def test_same_name_at_two_different_locations_is_allowed(self):
        # Real chains do have branches - the uniqueness that matters is (name, location).
        a = make_location("Sukkur", "Barrage Road")
        b = make_location("Khairpur", "Khairpur City")
        Hospital.objects.create(name="Test General Hospital", location=a)
        Hospital.objects.create(name="Test General Hospital", location=b)  # must not raise
        self.assertEqual(Hospital.objects.filter(name="Test General Hospital").count(), 2)

    def test_same_name_at_the_same_location_twice_is_rejected(self):
        location = make_location("Sukkur", "Barrage Road")
        Hospital.objects.create(name="Test General Hospital", location=location)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Hospital.objects.create(name="Test General Hospital", location=location)


class HospitalAccountModelTests(TestCase):
    def test_one_user_can_only_have_one_hospital_account(self):
        location = make_location("Sukkur", "Barrage Road")
        hospital = Hospital.objects.create(name="Test General Hospital", location=location)
        user = User.objects.create_user(username="staff1")
        HospitalAccount.objects.create(user=user, hospital=hospital, staff_name="Dr. A")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                HospitalAccount.objects.create(user=user, hospital=hospital, staff_name="Dr. B")

    def test_a_hospital_can_have_more_than_one_staff_account(self):
        location = make_location("Sukkur", "Barrage Road")
        hospital = Hospital.objects.create(name="Test General Hospital", location=location)
        HospitalAccount.objects.create(
            user=User.objects.create_user(username="staff1"), hospital=hospital, staff_name="Dr. A",
        )
        HospitalAccount.objects.create(
            user=User.objects.create_user(username="staff2"), hospital=hospital, staff_name="Dr. B",
        )  # must not raise
        self.assertEqual(hospital.staff_accounts.count(), 2)


class SeededHospitalListTests(TestCase):
    """These come from hospitals/migrations/0002_seed_hospitals.py, applied automatically
    when the test database is built - not from anything a test creates itself."""

    def test_the_fixed_hospital_list_is_present_after_migrations(self):
        self.assertGreaterEqual(Hospital.objects.count(), 9)

    def test_spans_more_than_one_city(self):
        cities = set(Hospital.objects.values_list("location__city", flat=True))
        self.assertGreater(len(cities), 1)


class SeededHospitalAccountsTests(TestCase):
    """These come from hospitals/migrations/0003_seed_hospital_accounts.py - every
    hospital in the fixed list gets a real, permanent login the moment
    `migrate` runs, so nothing in the dropdown is ever a dead end."""

    def test_every_hospital_has_exactly_one_login_account(self):
        for hospital in Hospital.objects.all():
            with self.subTest(hospital=hospital):
                self.assertEqual(HospitalAccount.objects.filter(hospital=hospital).count(), 1)

    def test_usernames_do_not_collide_with_the_older_hospital01_style_naming(self):
        # seed_demo_data used to create its own "hospital01"/"02"/"03" accounts for
        # a handful of hospitals; the permanent accounts must use a different
        # scheme so the two can never clash on an existing database.
        for account in HospitalAccount.objects.select_related("user"):
            self.assertFalse(account.user.username.startswith("hospital"))

    def test_passwords_are_unique_per_account_not_shared(self):
        passwords = list(HospitalAccount.objects.values_list("user__password", flat=True))
        self.assertEqual(len(passwords), len(set(passwords)))

    def test_password_is_set_and_usable_not_blank_or_unusable(self):
        for account in HospitalAccount.objects.select_related("user"):
            with self.subTest(account=account):
                self.assertTrue(account.user.has_usable_password())


class RotateSharedPasswordMigrationTests(TestCase):
    """hospitals/migrations/0004 fixes up any account still left on the old
    shared demo password. Every account is already unique by the time a test
    database is built, so this simulates the "before" state directly to
    actually exercise the rotation logic, rather than just trusting it never runs."""

    def test_an_account_still_on_the_old_shared_password_gets_rotated(self):
        from django.apps import apps as live_apps
        from django.contrib.auth.hashers import check_password
        import importlib
        migration_0004 = importlib.import_module(
            "hospitals.migrations.0004_rotate_shared_hospital_passwords"
        )

        account = HospitalAccount.objects.select_related("user").first()
        account.user.set_password(migration_0004.OLD_SHARED_PASSWORD)
        account.user.save()

        migration_0004.rotate_shared_passwords(live_apps, None)

        account.user.refresh_from_db()
        self.assertFalse(check_password(migration_0004.OLD_SHARED_PASSWORD, account.user.password))

    def test_an_account_already_on_a_unique_password_is_left_alone(self):
        import importlib
        migration_0004 = importlib.import_module(
            "hospitals.migrations.0004_rotate_shared_hospital_passwords"
        )
        from django.apps import apps as live_apps

        account = HospitalAccount.objects.select_related("user").first()
        original_hash = account.user.password  # already a unique random password from migration 0003

        migration_0004.rotate_shared_passwords(live_apps, None)

        account.user.refresh_from_db()
        self.assertEqual(account.user.password, original_hash)
