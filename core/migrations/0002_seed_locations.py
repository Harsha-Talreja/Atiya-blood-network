"""Data migration: preload the cities and areas the app supports.

A data migration runs automatically with `migrate` (and in the test database),
so the locations can never be forgotten. get_or_create makes it safe to re-run.
"""
from django.db import migrations

LOCATIONS = {
    "Sukkur": [
        "Military Road", "Barrage Road", "Minara Road", "Bunder Road",
        "Old Sukkur", "New Pind", "Airport Road", "Ghanta Ghar", "Other",
    ],
    "Rohri": [
        "Rohri City", "Rohri Junction", "Aror", "Lansdowne Bridge Area", "Other",
    ],
    "Khairpur": [
        "Khairpur City", "Kot Diji", "Gambat", "Faiz Ganj",
        "Thari Mirwah", "Kingri", "Nara", "Other",
    ],
    "Shikarpur": [
        "Shikarpur City", "Lakhi Ghulam Shah", "Garhi Yasin", "Khanpur", "Other",
    ],
    "Larkana": [
        "Larkana City", "Ratodero", "Dokri", "Bakrani", "Warah", "Naudero", "Other",
    ],
    "Ghotki": [
        "Ghotki City", "Daharki", "Mirpur Mathelo", "Ubauro", "Khangarh", "Other",
    ],
}


def seed_locations(apps, schema_editor):
    # Use the historical model, not a direct import, as migrations require.
    Location = apps.get_model("core", "Location")
    for city, areas in LOCATIONS.items():
        for area in areas:
            Location.objects.get_or_create(city=city, area=area)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        # noop reverse: rolling back must not delete locations donors may use.
        migrations.RunPython(seed_locations, migrations.RunPython.noop),
    ]
