from django.conf import settings
from django.db import models


class Hospital(models.Model):
    """A real hospital or blood bank. Requesters pick one of these rather than
    typing a name in free text, so verification can be routed to the right account."""

    name = models.CharField(max_length=150)
    location = models.ForeignKey(
        "core.Location", on_delete=models.PROTECT, related_name="hospitals"
    )

    class Meta:
        ordering = ["location__city", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "location"], name="unique_hospital_per_location"),
        ]

    def __str__(self):
        return f"{self.name} ({self.location.city})"


class HospitalAccount(models.Model):
    """Links a login (User) to the one hospital that account represents.

    One hospital can have more than one staff account (OneToOne is on the
    User side, not the Hospital side), but each account speaks for exactly
    one hospital, so a request can only ever be verified by its own hospital.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="hospital_account"
    )
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name="staff_accounts")
    staff_name = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.staff_name} @ {self.hospital}"
