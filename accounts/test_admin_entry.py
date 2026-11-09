"""Getting into the admin panel: who lands there, and how an account is given
access in the first place.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


@FAST_HASHER
class WhereLoginSendsYouTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("boss", password="pw", is_staff=True)
        self.ordinary = User.objects.create_user("plain", password="pw")

    def login(self, username, **extra):
        return self.client.post(
            reverse("accounts:login"), {"username": username, "password": "pw", **extra}
        )

    def test_an_admin_lands_on_the_admin_panel(self):
        response = self.login("boss")
        self.assertRedirects(response, reverse("siteadmin:overview"))

    def test_everyone_else_lands_on_their_dashboard(self):
        response = self.login("plain")
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_a_next_address_still_wins_for_an_admin(self):
        """Someone sent to log in from a particular page is returned to that
        page, rather than being pulled into the panel instead."""
        target = reverse("blood_requests:list")
        response = self.login("boss", next=target)
        self.assertRedirects(response, target)

    def test_an_offsite_next_address_is_ignored(self):
        response = self.login("boss", next="https://example.com/steal")
        self.assertRedirects(response, reverse("siteadmin:overview"))

    def test_an_admin_who_is_already_signed_in_is_sent_to_the_panel(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("accounts:login"))
        self.assertRedirects(response, reverse("siteadmin:overview"))


class MakeAdminCommandTests(TestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("make_admin", *args, stdout=out)
        return out.getvalue()

    def test_it_gives_an_existing_account_admin_access(self):
        user = User.objects.create_user("alice")
        self.assertFalse(user.is_staff)

        output = self.run_command("alice")

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertIn("alice is now an admin", output)

    def test_staff_only_withholds_django_admin(self):
        User.objects.create_user("bob")
        self.run_command("bob", "--staff-only")
        bob = User.objects.get(username="bob")
        self.assertTrue(bob.is_staff)
        self.assertFalse(bob.is_superuser)

    def test_remove_takes_the_access_away(self):
        User.objects.create_user("carol", is_staff=True, is_superuser=True)
        self.run_command("carol", "--remove")
        carol = User.objects.get(username="carol")
        self.assertFalse(carol.is_staff)
        self.assertFalse(carol.is_superuser)

    def test_an_unknown_name_says_which_accounts_exist(self):
        User.objects.create_user("dave")
        with self.assertRaises(CommandError) as caught:
            self.run_command("davee")
        message = str(caught.exception)
        self.assertIn("no account called 'davee'", message)
        self.assertIn("dave", message)  # the near miss is right there in the message

    def test_no_name_at_all_explains_what_to_type(self):
        with self.assertRaises(CommandError) as caught:
            self.run_command()
        self.assertIn("make_admin <username>", str(caught.exception))

    def test_list_shows_who_has_access(self):
        User.objects.create_user("erin", is_staff=True)
        User.objects.create_user("frank")
        output = self.run_command("--list")
        self.assertIn("erin", output)
        self.assertNotIn("frank", output)

    def test_list_on_a_fresh_database_says_how_to_fix_it(self):
        output = self.run_command("--list")
        self.assertIn("No account has admin access yet", output)
        self.assertIn("make_admin", output)
