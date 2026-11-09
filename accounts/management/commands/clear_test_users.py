"""Remove every donor and patient account so the site can be tried again from scratch.

Kept: admin and staff accounts, hospital logins, the hospital list and the city and
area list. Removed: every ordinary account with its donor profile, requests, offers,
notifications and CNIC record. Unlike deleting one user from the admin panel, this also
forgets the retired CNICs, so the same test CNIC can be used to register again.

    python manage.py clear_test_users          # shows what would go
    python manage.py clear_test_users --yes    # does it
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import RetiredCnic
from blood_requests.models import BloodRequest, DonorResponse
from donors.models import DonorProfile
from siteadmin.selectors import ordinary_users

User = get_user_model()


class Command(BaseCommand):
    help = "Delete all donor and patient accounts (keeps admins and hospital logins)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Actually delete. Without it, only counts are shown.")

    def handle(self, *args, **options):
        users = ordinary_users().filter(is_superuser=False)
        counts = {
            "accounts": users.count(),
            "donor profiles": DonorProfile.objects.filter(user__in=users).count(),
            "requests": BloodRequest.objects.filter(requester__in=users).count(),
            "offers": DonorResponse.objects.filter(donor__user__in=users).count(),
            "retired CNICs": RetiredCnic.objects.count(),
        }
        kept = User.objects.exclude(pk__in=users.values("pk")).count()
        for label, number in counts.items():
            self.stdout.write(f"  {label}: {number}")
        self.stdout.write(f"  admin and hospital logins kept: {kept}")
        if not options["yes"]:
            self.stdout.write(self.style.WARNING("Nothing deleted. Run again with --yes to delete."))
            return
        with transaction.atomic():
            users.delete()
            RetiredCnic.objects.all().delete()
        self.stdout.write(self.style.SUCCESS("Done. Donors and patients are gone; admins and hospitals are untouched."))
