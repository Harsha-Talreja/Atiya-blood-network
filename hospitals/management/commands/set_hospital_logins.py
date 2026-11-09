"""Give every hospital a memorable username and a password you choose.

`migrate` already creates one login per hospital (hosp01, hosp02, ...) with a
random password that is printed once and never shown again. That is secure but
awkward when you need to log in during a demo. This command renames each
hospital's login to something readable (civilhospital_sukkur, ...) and sets a
password you know.

    python manage.py set_hospital_logins
    python manage.py set_hospital_logins --password "SomethingElse1!"

Safe to run again. It only touches hospital staff accounts, and it will not
take over a username that already belongs to someone else.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from hospitals.models import Hospital, HospitalAccount

User = get_user_model()

DEFAULT_PASSWORD = "Hospital@2026"

# Keyed by the exact Hospital.name from hospitals/migrations/0002_seed_hospitals.py.
USERNAMES = {
    "Civil Hospital": "civilhospital_sukkur",
    "Civil Hospital Khairpur": "civilhospital_khairpur",
    "Ghulam Muhammad Mahar Medical College Hospital": "gmmmc_sukkur",
    "Al-Khidmat Blood Bank": "alkhidmat_sukkur",
    "Rohri Taluka Hospital": "rohritaluka_rohri",
    "Khairpur Medical College Hospital": "khairpurmedical_khairpur",
    "Shikarpur Civil Hospital": "shikarpurcivil_shikarpur",
    "Chandka Medical College Hospital": "chandkamedical_larkana",
    "Ghotki Civil Hospital": "ghotkicivil_ghotki",
}


class Command(BaseCommand):
    help = "Give each hospital a memorable username and a known password."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password", default=DEFAULT_PASSWORD,
            help=f"Password to set on every hospital login (default: {DEFAULT_PASSWORD}).",
        )

    def handle(self, *args, **options):
        password = options["password"]
        done, skipped = [], []

        with transaction.atomic():
            for hospital in Hospital.objects.select_related("location").order_by("location__city", "name"):
                username = USERNAMES.get(hospital.name)
                label = f"{hospital.name} ({hospital.location.city})"
                if username is None:
                    skipped.append(f"{label}: not in the known hospital list, left alone")
                    continue

                account = HospitalAccount.objects.select_related("user").filter(hospital=hospital).first()
                if account is None:
                    # This hospital has no login yet: make one, unless the name is already taken.
                    if User.objects.filter(username=username).exists():
                        skipped.append(f"{label}: username '{username}' belongs to someone else, skipped")
                        continue
                    user = User.objects.create(username=username, email=f"{username}@bloodnetwork.local")
                    account = HospitalAccount.objects.create(
                        user=user, hospital=hospital, staff_name=f"{hospital.name} Verification Desk",
                    )
                else:
                    clash = User.objects.filter(username=username).exclude(pk=account.user_id).exists()
                    if clash:
                        skipped.append(f"{label}: username '{username}' belongs to someone else, skipped")
                        continue
                    account.user.username = username

                account.user.set_password(password)
                account.user.save()
                done.append((username, label))

        for username, label in done:
            self.stdout.write(f"  {username:<28} {label}")
        for note in skipped:
            self.stdout.write(self.style.WARNING(f"  skipped - {note}"))
        self.stdout.write(self.style.SUCCESS(
            f"\nSet {len(done)} hospital login(s). Password for all of them: {password}"
        ))
