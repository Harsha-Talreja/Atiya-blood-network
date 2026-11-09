from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_identity"),
    ]

    operations = [
        migrations.CreateModel(
            name="RetiredCnic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cnic_hash", models.CharField(max_length=64, unique=True)),
                ("retired_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "retired CNIC",
                "verbose_name_plural": "retired CNICs",
            },
        ),
    ]
