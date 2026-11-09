"""Seed a demo-ready database: an admin, a demo requester, ~30 donors across
three cities, and ~12 requests covering every status, urgency, blood type,
and verification state.

Hospital login accounts are NOT created here - every hospital already has a
real, permanent login from hospitals/migrations/0003_seed_hospital_accounts.py.
That keeps hospital logins out of what --reset can ever delete.

Safe to run more than once: with no flags, if the demo accounts already exist it
does nothing and tells you so. Pass --reset to wipe just the demo-tagged accounts
(and everything that cascades from them - donor profiles, requests, responses)
and recreate them fresh. Real accounts, Locations and Hospitals are never touched.

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --reset
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from blood_requests.models import BloodRequest
from core.constants import BLOOD_TYPES, STATUS_FULFILLED
from core.models import Location
from donors.models import DonorProfile
from hospitals.models import Hospital, HospitalAccount

User = get_user_model()

DEMO_PASSWORD = "Demo@12345"
ADMIN_USERNAME = "demo_admin"
DEMO_REQUESTER_USERNAME = "demo_user"
DONOR_COUNT = 30
DONOR_CITIES = ["Sukkur", "Khairpur", "Rohri"]

# Usernames for every account this command creates, so --reset knows exactly
# what to remove without touching anyone else's real account. Hospital
# accounts are deliberately NOT in this list - see the module docstring.
DONOR_USERNAMES = [f"donor{i:02d}" for i in range(1, DONOR_COUNT + 1)]
ALL_DEMO_USERNAMES = [ADMIN_USERNAME, DEMO_REQUESTER_USERNAME, *DONOR_USERNAMES]

FIRST_NAMES = [
    "Ali", "Ahmed", "Bilal", "Danish", "Faisal", "Hamza", "Imran", "Junaid",
    "Kamran", "Moiz", "Nadeem", "Omar", "Qasim", "Rashid", "Saad", "Tariq",
    "Usman", "Waqas", "Yasir", "Zeeshan", "Ayesha", "Bushra", "Fatima", "Hina",
    "Iqra", "Kiran", "Mehak", "Nida", "Sana", "Zainab",
]
LAST_NAMES = [
    "Raza", "Khan", "Memon", "Shaikh", "Soomro", "Abbasi", "Chandio", "Brohi",
    "Junejo", "Lashari", "Mahar", "Panhwar", "Qureshi", "Shar",
]

# (patient_name, hospital name, blood_type, urgency, "pending"|"expired"|"fulfilled", verified)
# Hospital names must match ones from hospitals/migrations/0002_seed_hospitals.py.
# A few are left unverified-and-pending on purpose, so their hospital's real
# login account (see migration 0003) always has something real to verify.
DEMO_REQUESTS = [
    ("Sana Bibi", "Civil Hospital", "O-", "Critical", "pending", False),
    ("Ahmed Ali", "Ghulam Muhammad Mahar Medical College Hospital", "A+", "Urgent", "pending", True),
    ("Fatima Khatoon", "Al-Khidmat Blood Bank", "B+", "Normal", "pending", True),
    ("Zubair Ahmed", "Khairpur Medical College Hospital", "AB+", "Critical", "pending", False),
    ("Nazia Parveen", "Civil Hospital Khairpur", "A-", "Urgent", "pending", True),
    ("Imran Soomro", "Rohri Taluka Hospital", "O+", "Normal", "pending", False),
    ("Kiran Shaikh", "Civil Hospital", "B-", "Critical", "expired", True),
    ("Waqas Memon", "Khairpur Medical College Hospital", "AB-", "Urgent", "expired", True),
    ("Hina Junejo", "Rohri Taluka Hospital", "A+", "Normal", "expired", True),
    ("Bilal Chandio", "Civil Hospital", "O-", "Urgent", "fulfilled", True),
    ("Ayesha Lashari", "Khairpur Medical College Hospital", "B+", "Normal", "fulfilled", True),
    ("Danish Brohi", "Rohri Taluka Hospital", "O+", "Critical", "fulfilled", True),
]


class Command(BaseCommand):
    help = "Seed a demo-ready database with an admin, a demo user, ~30 donors and ~12 requests."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete the existing demo accounts (and their donor profiles / requests) first, then recreate them.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._wipe_demo_data()
        elif User.objects.filter(username=ADMIN_USERNAME).exists():
            self.stdout.write(self.style.WARNING(
                "Demo data already exists (a 'demo_admin' account is present) - nothing to do.\n"
                "Run with --reset to wipe the demo accounts and recreate them."
            ))
            return

        self._check_hospitals_are_seeded()

        with transaction.atomic():
            self._create_admin_and_demo_user()
            donors = self._create_donors()
            self._create_requests(donors)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {DONOR_COUNT} donors and {len(DEMO_REQUESTS)} requests "
            f"({sum(1 for *_, verified in DEMO_REQUESTS if not verified)} awaiting hospital verification).\n\n"
            "Demo logins (all use the same password):\n"
            f"  Admin:     username={ADMIN_USERNAME}  password={DEMO_PASSWORD}\n"
            f"  Requester: username={DEMO_REQUESTER_USERNAME}  password={DEMO_PASSWORD}\n"
            f"  Any donor: username=donor01..donor{DONOR_COUNT:02d}  password={DEMO_PASSWORD}\n\n"
            "Hospital logins were already created when you ran 'migrate' - "
            "see the output from that command, or check the Django admin under Hospitals > Hospital accounts."
        ))

    def _check_hospitals_are_seeded(self):
        # These come from hospitals/migrations/0002_seed_hospitals.py, applied by
        # `migrate`. If they're missing, migrations haven't been run yet - fail
        # with a clear message rather than a confusing crash partway through.
        if not Hospital.objects.exists():
            raise CommandError(
                "No hospitals found. Run 'python manage.py migrate' first "
                "(this seeds the fixed hospital list), then try again."
            )

    def _wipe_demo_data(self):
        # Deleting the Users cascades to their DonorProfile, BloodRequest (as
        # requester) and DonorResponse rows. Locations, Hospitals, hospital
        # login accounts, and any non-demo accounts are left alone.
        deleted, _ = User.objects.filter(username__in=ALL_DEMO_USERNAMES).delete()
        if deleted:
            self.stdout.write(f"Removed {deleted} existing demo-related rows.")

    def _create_admin_and_demo_user(self):
        User.objects.create_superuser(ADMIN_USERNAME, "admin@bloodnetwork.local", DEMO_PASSWORD)
        User.objects.create_user(DEMO_REQUESTER_USERNAME, "demo@bloodnetwork.local", DEMO_PASSWORD)

    def _create_donors(self):
        """~30 donors spread across the three cities and all eight blood types,
        with a mix of availability and cooldown status so search and matching
        have something interesting to show."""
        locations = list(Location.objects.filter(city__in=DONOR_CITIES))
        rng = random.Random(42)  # fixed seed: same demo data every time, still varied
        names = rng.sample(
            [f"{first} {last}" for first in FIRST_NAMES for last in LAST_NAMES],
            DONOR_COUNT,
        )

        donors = []
        for i, username in enumerate(DONOR_USERNAMES):
            user = User.objects.create_user(username, f"{username}@bloodnetwork.local", DEMO_PASSWORD)
            blood_type = BLOOD_TYPES[i % len(BLOOD_TYPES)]
            location = rng.choice(locations)

            # Roughly: 1/3 never donated (immediately eligible), 1/3 past cooldown,
            # 1/6 still resting, and the rest available-but-unavailable-toggle mixed in.
            roll = i % 6
            if roll in (0, 1):
                last_donation = None
            elif roll in (2, 3):
                last_donation = timezone.localdate() - timedelta(days=rng.randint(91, 300))
            else:
                last_donation = timezone.localdate() - timedelta(days=rng.randint(1, 60))
            is_available = roll != 5  # one in six switched off, so availability filtering has something to show

            donors.append(DonorProfile.objects.create(
                user=user, full_name=names[i], phone="03" + str(rng.randint(0, 9)) + str(rng.randint(10000000, 99999999)),
                blood_type=blood_type, location=location, is_available=is_available,
                phone_consent=True, eligibility_declared=True, last_donation_date=last_donation,
            ))
        return donors

    def _create_requests(self, donors):
        requester_pool = [User.objects.get(username=DEMO_REQUESTER_USERNAME)] + [d.user for d in donors[:3]]
        now = timezone.now()

        for i, (patient, hospital_name, blood_type, urgency, kind, verified) in enumerate(DEMO_REQUESTS):
            # Hospital names aren't guaranteed globally unique (a chain can have branches
            # at different locations) - take the first match rather than risk a crash.
            hospital = Hospital.objects.select_related("location").filter(name=hospital_name).order_by("pk").first()
            if hospital is None:
                continue  # hospital list has changed since this was written; skip rather than crash
            requester = requester_pool[i % len(requester_pool)]

            extra = {}
            if kind == "expired":
                extra["expires_at"] = now - timedelta(hours=2)
            elif kind == "fulfilled":
                extra["status"] = STATUS_FULFILLED
                extra["fulfilled_at"] = now - timedelta(hours=5)

            if verified:
                verifier = HospitalAccount.objects.filter(hospital=hospital).select_related("user").first()
                extra["is_verified"] = True
                extra["verified_at"] = now - timedelta(hours=10)
                extra["verified_by"] = verifier.user if verifier else None

            BloodRequest.objects.create(
                requester=requester, patient_name=patient, blood_type=blood_type,
                units_needed=random.Random(i).randint(1, 3), urgency=urgency,
                hospital=hospital, location=hospital.location, contact_phone="03001234567",
                note="", **extra,
            )
