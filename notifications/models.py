"""In-app notifications: a row per important event, kept until the person reads it.

Deliberately not email or SMS: nothing leaves the site, so there is nothing to
pay for and nothing private is sent anywhere. A notification only says that
something happened and links to the page where the person can act on it.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    # What happened. Stored as a short code so the wording can be changed later
    # without rewriting history, and so tests can ask for "all donor responses".
    DONOR_RESPONSE = "donor_response"
    REQUEST_FOR_HOSPITAL = "request_for_hospital"
    HOSPITAL_VERIFIED = "hospital_verified"
    ADMIN_RELEASED = "admin_released"
    ADMIN_APPROVED = "admin_approved"
    ADMIN_REJECTED = "admin_rejected"
    EXTRA_APPROVED = "extra_approved"
    EXTRA_REJECTED = "extra_rejected"
    NEEDS_REVIEW = "needs_review"
    TIMED_OUT = "timed_out"
    FULFILLED = "fulfilled"
    NEW_MATCH = "new_match"
    KIND_CHOICES = [
        (DONOR_RESPONSE, "A donor offered to help"),
        (REQUEST_FOR_HOSPITAL, "A request names your hospital"),
        (HOSPITAL_VERIFIED, "A hospital verified a request"),
        (ADMIN_RELEASED, "An admin released a request"),
        (ADMIN_APPROVED, "An admin approved a request"),
        (ADMIN_REJECTED, "An admin rejected a request"),
        (EXTRA_APPROVED, "Extra units approved"),
        (EXTRA_REJECTED, "Extra units rejected"),
        (NEEDS_REVIEW, "Extra units need a decision"),
        (TIMED_OUT, "A hospital missed its deadline"),
        (FULFILLED, "A request was fulfilled"),
        (NEW_MATCH, "A new request matches you"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    message = models.CharField(max_length=240)
    # Where "Open" goes. A relative path, never user input.
    url = models.CharField(max_length=200, blank=True)
    # SET_NULL: removing a request must not silently delete what people were told about it.
    request = models.ForeignKey(
        "blood_requests.BloodRequest", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return f"{self.user_id}: {self.message}"

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_read(self):
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])
