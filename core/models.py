from django.db import models


class Location(models.Model):
    """A city + area pair. Donors and requests point to one, so matching
    compares IDs instead of free-typed text (no 'Sukkur' vs 'sukkur' mismatches)."""

    city = models.CharField(max_length=60)
    area = models.CharField(max_length=80)

    class Meta:
        ordering = ["city", "area"]
        constraints = [
            # Modern equivalent of unique_together.
            models.UniqueConstraint(fields=["city", "area"], name="unique_city_area"),
        ]

    def __str__(self):
        return f"{self.area}, {self.city}"
