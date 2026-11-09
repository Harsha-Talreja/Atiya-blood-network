"""Tests for the set_hospital_logins management command."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from hospitals.management.commands.set_hospital_logins import DEFAULT_PASSWORD, USERNAMES
from hospitals.models import Hospital, HospitalAccount

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


def run(*args):
    out = StringIO()
    call_command("set_hospital_logins", *args, stdout=out)
    return out.getvalue()


@FAST_HASHER
class SetHospitalLoginsTests(TestCase):
    def test_every_hospital_gets_its_memorable_username(self):
        run()
        for hospital in Hospital.objects.all():
            with self.subTest(hospital=hospital.name):
                account = HospitalAccount.objects.get(hospital=hospital)
                self.assertEqual(account.user.username, USERNAMES[hospital.name])

    def test_each_login_works_with_the_default_password(self):
        run()
        for username in USERNAMES.values():
            with self.subTest(username=username):
                self.assertTrue(self.client.login(username=username, password=DEFAULT_PASSWORD))
                self.client.logout()

    def test_a_custom_password_can_be_chosen(self):
        run("--password", "MyOwnPass#1")
        self.assertTrue(self.client.login(username="civilhospital_sukkur", password="MyOwnPass#1"))
        self.assertFalse(self.client.login(username="civilhospital_sukkur", password=DEFAULT_PASSWORD))

    def test_running_it_twice_changes_nothing_structural(self):
        run()
        accounts_before = HospitalAccount.objects.count()
        users_before = User.objects.count()
        run()
        self.assertEqual(HospitalAccount.objects.count(), accounts_before)
        self.assertEqual(User.objects.count(), users_before)

    def test_a_hospital_with_no_login_gets_one(self):
        HospitalAccount.objects.filter(hospital__name="Ghotki Civil Hospital").delete()
        run()
        account = HospitalAccount.objects.get(hospital__name="Ghotki Civil Hospital")
        self.assertEqual(account.user.username, "ghotkicivil_ghotki")
        self.assertTrue(self.client.login(username="ghotkicivil_ghotki", password=DEFAULT_PASSWORD))

    def test_it_never_takes_over_someone_elses_username(self):
        # A real person already signed up with this exact name.
        stranger = User.objects.create_user("civilhospital_sukkur", password="their-own-password")
        output = run()
        stranger.refresh_from_db()
        self.assertTrue(stranger.check_password("their-own-password"))
        self.assertFalse(HospitalAccount.objects.filter(user=stranger).exists())
        self.assertIn("belongs to someone else", output)

    def test_it_leaves_ordinary_accounts_alone(self):
        person = User.objects.create_user("some_donor", password="donor-password")
        run()
        person.refresh_from_db()
        self.assertEqual(person.username, "some_donor")
        self.assertTrue(person.check_password("donor-password"))

    def test_a_hospital_outside_the_known_list_is_left_alone(self):
        from blood_requests.tests import make_hospital, make_location
        extra = make_hospital("Brand New Clinic", make_location("Sukkur", "Military Road"))
        user = User.objects.create_user("clinic_staff", password="clinic-password")
        HospitalAccount.objects.create(user=user, hospital=extra, staff_name="Clinic Desk")
        output = run()
        user.refresh_from_db()
        self.assertEqual(user.username, "clinic_staff")
        self.assertTrue(user.check_password("clinic-password"))
        self.assertIn("not in the known hospital list", output)
