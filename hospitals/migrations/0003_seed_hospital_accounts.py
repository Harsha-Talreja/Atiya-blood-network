"""Give every hospital in the fixed list its own real login account, so any
hospital chosen in the request form actually has someone who can verify
requests sent to it.

This is permanent infrastructure, not demo/test data: it's seeded here (like
the hospital list itself) rather than by seed_demo_data, so it is never
deleted by clearing demo accounts. Usernames are "hosp01", "hosp02", ... in
(city, name) order - deliberately NOT "hospital01" etc., since that scheme
was already used by seed_demo_data for a handful of hospitals and reusing it
here could collide with an existing account tied to a *different* hospital.
Idempotent: skips any hospital that already has a staff account (e.g. if this
runs on a database where some hospitals were set up by hand first).

Each account gets its own random password (not a shared one) - if any single
hospital's login leaks, the rest stay safe. There's no way to recover a
password after this runs; the printed output is the only record of it.
"""
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations
from django.utils.crypto import get_random_string

# Avoids visually ambiguous characters (0/O, 1/l/I) since a human may need to
# type these out from a terminal.
PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


def seed_hospital_accounts(apps, schema_editor):
    Hospital = apps.get_model("hospitals", "Hospital")
    HospitalAccount = apps.get_model("hospitals", "HospitalAccount")
    User = apps.get_model(settings.AUTH_USER_MODEL)

    hospitals = Hospital.objects.select_related("location").order_by("location__city", "name")
    created = []
    for i, hospital in enumerate(hospitals, start=1):
        if HospitalAccount.objects.filter(hospital=hospital).exists():
            continue

        username = f"hosp{i:02d}"
        # Guard against a username collision with some unrelated existing account
        # (e.g. a real person who happens to have signed up as "hosp01" already).
        suffix = 2
        base_username = username
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{suffix}"
            suffix += 1

        password = get_random_string(12, PASSWORD_ALPHABET)
        user = User.objects.create(
            username=username, email=f"{username}@bloodnetwork.local", password=make_password(password),
        )
        HospitalAccount.objects.create(
            user=user, hospital=hospital, staff_name=f"{hospital.name} Verification Desk",
        )
        created.append((username, password, f"{hospital.name} ({hospital.location.city})"))

    if created:
        print(f"\n  Seeded {len(created)} hospital login account(s) - record these now, they can't be shown again:")
        for username, password, hospital_label in created:
            print(f"    {username}  /  {password}   ({hospital_label})")


class Migration(migrations.Migration):
    dependencies = [
        ("hospitals", "0002_seed_hospitals"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # No reverse: these are real login accounts by the time anyone would roll
        # this back, and reversing shouldn't silently delete someone's account.
        migrations.RunPython(seed_hospital_accounts, migrations.RunPython.noop),
    ]
