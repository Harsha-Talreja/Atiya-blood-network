"""Turn an existing account into an admin.

Django decides who is an admin with the is_staff flag, not with the username, so
an account called "admin" is still an ordinary user until that flag is set. That
is a reasonable rule, but it is a confusing first hour, and the alternative was
asking people to paste a long one-liner into manage.py shell. This is that
one-liner with a name and an error message.

    python manage.py make_admin alice
    python manage.py make_admin alice --staff-only
    python manage.py make_admin --list
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Give an existing account access to the admin panel."

    def add_arguments(self, parser):
        parser.add_argument(
            "username", nargs="?", help="The account to promote."
        )
        parser.add_argument(
            "--staff-only",
            action="store_true",
            help="Admin panel only, without access to Django admin.",
        )
        parser.add_argument(
            "--remove",
            action="store_true",
            help="Take admin access away again.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="Show who currently has admin access.",
        )

    def handle(self, *args, **options):
        if options["list"]:
            return self._list()

        username = options["username"]
        if not username:
            raise CommandError(
                "Which account? Try:  python manage.py make_admin <username>\n"
                "To see the accounts you have:  python manage.py make_admin --list"
            )

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            known = list(User.objects.order_by("username").values_list("username", flat=True)[:12])
            raise CommandError(
                f"There is no account called {username!r}.\n"
                f"Accounts in this database: {', '.join(known) or 'none yet'}\n"
                "To create one:  python manage.py createsuperuser"
            )

        if options["remove"]:
            user.is_staff = False
            user.is_superuser = False
            user.save(update_fields=["is_staff", "is_superuser"])
            self.stdout.write(
                self.style.WARNING(f"{user.username} can no longer open the admin panel.")
            )
            return

        user.is_staff = True
        user.is_superuser = not options["staff_only"]
        user.save(update_fields=["is_staff", "is_superuser"])

        self.stdout.write(self.style.SUCCESS(f"{user.username} is now an admin."))
        self.stdout.write("  Admin panel:  yes")
        self.stdout.write(f"  Django admin: {'yes' if user.is_superuser else 'no'}")
        self.stdout.write("")
        self.stdout.write(
            "Log out and back in, and you will land on the admin panel at /admin-panel/."
        )

    def _list(self):
        admins = User.objects.filter(is_staff=True).order_by("username")
        if not admins:
            self.stdout.write("No account has admin access yet.")
            self.stdout.write("Give one access with:  python manage.py make_admin <username>")
            return
        self.stdout.write("Accounts that can open the admin panel:")
        for user in admins:
            extra = " (also Django admin)" if user.is_superuser else ""
            self.stdout.write(f"  {user.username}{extra}")
