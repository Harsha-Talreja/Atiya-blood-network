from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.constants import BLOOD_TYPE_CHOICES
from core.validators import phone_validator, validate_not_in_future
from donors import eligibility


class DonorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="donor_profile"
    )
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, validators=[phone_validator])
    blood_type = models.CharField(max_length=3, choices=BLOOD_TYPE_CHOICES)
    location = models.ForeignKey(
        "core.Location", on_delete=models.PROTECT, related_name="donors"
    )
    is_available = models.BooleanField(default=True)
    # Privacy and safety declarations made when registering (the brief asks for an eligibility self-declaration).
    phone_consent = models.BooleanField(
        default=False, help_text="Agreed that signed-in people with a matching request may see this phone number."
    )
    eligibility_declared = models.BooleanField(
        default=False, help_text="Confirmed: 18 or older, in good health, and understands the blood bank will screen them."
    )
    last_donation_date = models.DateField(
        null=True, blank=True, validators=[validate_not_in_future]
    )
    # Basic health answers the donor gives about themselves. They are the donor's own words,
    # not a medical check: the hospital or blood bank still screens every donor. Left empty
    # on profiles made before these fields existed (the form asks for them on the next edit).
    weight_kg = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(30), MaxValueValidator(250)]
    )
    height_cm = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(100), MaxValueValidator(230)]
    )
    # No longer asked on the form or shown anywhere. The columns stay so that no migration is needed.
    blood_pressure = models.CharField(max_length=7, blank=True, help_text="Like 120/80. Empty if not known.")
    blood_sugar = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(30), MaxValueValidator(600)],
        help_text="mg/dL. Empty if not checked.",
    )
    # Comma-separated keys from donors.health.CONDITIONS, e.g. "diabetes,other". "none" means no known condition.
    conditions = models.CharField(max_length=120, blank=True)
    conditions_other = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["blood_type", "is_available"])]

    def __str__(self):
        return f"{self.full_name} ({self.blood_type})"

    @property
    def next_eligible_date(self):
        return eligibility.next_eligible_date(self.last_donation_date)

    @property
    def is_eligible(self):
        return eligibility.is_eligible(self.last_donation_date)

    @property
    def days_until_eligible(self):
        return eligibility.days_until_eligible(self.last_donation_date)

    @property
    def cooldown_progress(self):
        return eligibility.cooldown_progress(self.last_donation_date)

    @property
    def condition_keys(self):
        return [key for key in self.conditions.split(",") if key]

    @property
    def condition_labels(self):
        """Readable names for the saved conditions, with 'Other' replaced by what the donor typed."""
        from donors.health import CONDITION_LABELS
        labels = []
        for key in self.condition_keys:
            if key == "other" and self.conditions_other:
                labels.append(self.conditions_other)
            else:
                labels.append(CONDITION_LABELS.get(key, key))
        return labels

    @property
    def has_health_details(self):
        """True once the donor has answered the health questions (weight, height and conditions)."""
        return bool(self.weight_kg and self.height_cm and self.conditions)
