"""Data migration: preload the fixed list of hospitals requesters can pick from.

Mirrors core/migrations/0002_seed_locations.py: get_or_create makes it safe to
re-run, and the reverse migration is a no-op so rolling back never deletes a
hospital a request or staff account may already point to.
"""
from django.db import migrations

# (hospital name, city, area) - area must already exist for that city (see
# core/migrations/0002_seed_locations.py).
HOSPITALS = [
    ("Civil Hospital", "Sukkur", "Barrage Road"),
    ("Ghulam Muhammad Mahar Medical College Hospital", "Sukkur", "Airport Road"),
    ("Al-Khidmat Blood Bank", "Sukkur", "Minara Road"),
    ("Rohri Taluka Hospital", "Rohri", "Rohri City"),
    ("Khairpur Medical College Hospital", "Khairpur", "Khairpur City"),
    ("Civil Hospital Khairpur", "Khairpur", "Khairpur City"),
    ("Shikarpur Civil Hospital", "Shikarpur", "Shikarpur City"),
    ("Chandka Medical College Hospital", "Larkana", "Larkana City"),
    ("Ghotki Civil Hospital", "Ghotki", "Ghotki City"),
]


def seed_hospitals(apps, schema_editor):
    Location = apps.get_model("core", "Location")
    Hospital = apps.get_model("hospitals", "Hospital")
    for name, city, area in HOSPITALS:
        location = Location.objects.get(city=city, area=area)
        Hospital.objects.get_or_create(name=name, location=location)


class Migration(migrations.Migration):
    dependencies = [
        ("hospitals", "0001_initial"),
        ("core", "0002_seed_locations"),
    ]

    operations = [
        migrations.RunPython(seed_hospitals, migrations.RunPython.noop),
    ]
