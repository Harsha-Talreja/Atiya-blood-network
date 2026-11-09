"""Convert BloodRequest.hospital from free text to a proper Hospital FK, and add
verified_by / verified_at.

Data-preserving: every existing request's hospital text is turned into (or matched
to) a real Hospital row in the request's own city before the old text column is
dropped, so no request loses its hospital name across this migration.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def hospital_text_to_fk(apps, schema_editor):
    BloodRequest = apps.get_model("blood_requests", "BloodRequest")
    Hospital = apps.get_model("hospitals", "Hospital")
    for req in BloodRequest.objects.all():
        name = (req.hospital_old or "").strip() or "Unspecified hospital"
        hospital, _ = Hospital.objects.get_or_create(name=name, location=req.location)
        req.hospital = hospital
        req.save(update_fields=["hospital"])


def hospital_fk_to_text(apps, schema_editor):
    # Reverse: put the hospital's name back into the text field.
    BloodRequest = apps.get_model("blood_requests", "BloodRequest")
    for req in BloodRequest.objects.select_related("hospital").all():
        req.hospital_old = req.hospital.name if req.hospital_id else ""
        req.save(update_fields=["hospital_old"])


class Migration(migrations.Migration):
    dependencies = [
        ("blood_requests", "0001_initial"),
        ("hospitals", "0002_seed_hospitals"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Free the name "hospital" by renaming the old text column out of the way.
        migrations.RenameField(model_name="bloodrequest", old_name="hospital", new_name="hospital_old"),
        # 2. Add the real FK, nullable for now so the data migration can populate it.
        migrations.AddField(
            model_name="bloodrequest",
            name="hospital",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="blood_requests", to="hospitals.hospital",
            ),
        ),
        # 3. Populate hospital from hospital_old (creating Hospital rows as needed).
        migrations.RunPython(hospital_text_to_fk, hospital_fk_to_text),
        # 4. Every row now has a hospital; drop the old text column and require the FK.
        migrations.RemoveField(model_name="bloodrequest", name="hospital_old"),
        migrations.AlterField(
            model_name="bloodrequest",
            name="hospital",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="blood_requests", to="hospitals.hospital",
            ),
        ),
        # 5. Verification metadata anticipated in PROJECT_CONTEXT.md but never added.
        migrations.AddField(
            model_name="bloodrequest",
            name="verified_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="verified_requests", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="bloodrequest",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
