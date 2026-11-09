"""One-time fixup: hospitals/migrations/0003 originally gave every hospital
account the same shared password. If that already ran on this database, this
rotates each of those accounts to its own unique password.

Safe to run more than once and safe on a database that never had the shared
password: only touches accounts still set to the old shared value.
"""
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import migrations
from django.utils.crypto import get_random_string

OLD_SHARED_PASSWORD = "Demo@12345"
PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


def rotate_shared_passwords(apps, schema_editor):
    HospitalAccount = apps.get_model("hospitals", "HospitalAccount")

    rotated = []
    for account in HospitalAccount.objects.select_related("user", "hospital", "hospital__location"):
        user = account.user
        if not check_password(OLD_SHARED_PASSWORD, user.password):
            continue  # already unique (freshly created, or already rotated)

        password = get_random_string(12, PASSWORD_ALPHABET)
        user.password = make_password(password)
        user.save(update_fields=["password"])
        rotated.append((user.username, password, f"{account.hospital.name} ({account.hospital.location.city})"))

    if rotated:
        print(f"\n  Rotated {len(rotated)} hospital account(s) off the shared password - record these now:")
        for username, password, hospital_label in rotated:
            print(f"    {username}  /  {password}   ({hospital_label})")


class Migration(migrations.Migration):
    dependencies = [
        ("hospitals", "0003_seed_hospital_accounts"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(rotate_shared_passwords, migrations.RunPython.noop),
    ]
