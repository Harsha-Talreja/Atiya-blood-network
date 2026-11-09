from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext

from blood_requests.visibility import max_units_per_request, wait_minutes_for
from core.constants import (
    ADMIN_APPROVED_LABEL,
    ADMIN_RELEASED_LABEL,
    BLOOD_TYPE_CHOICES,
    EXTRA_APPROVED,
    EXTRA_NONE,
    EXTRA_PENDING,
    EXTRA_REJECTED,
    EXTRA_REVIEW_CHOICES,
    UNITS_HARD_CAP,
    REPORT_REASON_CHOICES,
    REQUEST_STATUS_CHOICES,
    STATUS_EXPIRED,
    STATUS_PENDING,
    TIMEOUT_APPROVED,
    TIMEOUT_NONE,
    TIMEOUT_REJECTED,
    TIMEOUT_REVIEW_CHOICES,
    URGENCY_CHOICES,
    URGENCY_HOURS,
    URGENCY_NORMAL,
)
from core.validators import phone_validator


class BloodRequest(models.Model):
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blood_requests"
    )
    patient_name = models.CharField(max_length=100)
    blood_type = models.CharField(max_length=3, choices=BLOOD_TYPE_CHOICES)
    units_needed = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(UNITS_HARD_CAP)]
    )
    urgency = models.CharField(max_length=10, choices=URGENCY_CHOICES, default=URGENCY_NORMAL)
    hospital = models.ForeignKey(
        "hospitals.Hospital", on_delete=models.PROTECT, related_name="blood_requests"
    )
    location = models.ForeignKey(
        "core.Location", on_delete=models.PROTECT, related_name="blood_requests"
    )
    contact_phone = models.CharField(max_length=15, validators=[phone_validator])
    note = models.TextField(blank=True)
    # "Additional Message / Reason for Extra Blood". Optional within the unit
    # limit, required above it (the form enforces that). Hospital staff and admins
    # read it; it is never shown on the public board.
    extra_reason = models.TextField(blank=True)
    # Set by save() the first time a request is stored: asking for more than the
    # standard limit makes it "pending", and nothing else can make it visible
    # until an admin decides. See is_visible_to_donors and selectors.open_requests.
    extra_review = models.CharField(
        max_length=10, choices=EXTRA_REVIEW_CHOICES, default=EXTRA_NONE, editable=False
    )
    review_note = models.TextField(blank=True, editable=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_requests", editable=False,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    status = models.CharField(max_length=10, choices=REQUEST_STATUS_CHOICES, default=STATUS_PENDING)
    # editable=False: set by save(), never by a form, so users can't extend their own deadline.
    expires_at = models.DateTimeField(editable=False)
    # A request is hidden from the public board and from donor matching until its own
    # hospital verifies it (see hospitals.views.verify). Owner and admin can still see it.
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="verified_requests",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    # An admin sending a request out BEFORE its wait is over, for a Critical case
    # where the minutes matter. Deliberately separate from is_verified: nobody has
    # checked this request, so the public badge must not say anyone has.
    released_early = models.BooleanField(default=False)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="released_requests",
    )
    released_at = models.DateTimeField(null=True, blank=True)
    # When the hospital misses its deadline the request waits for an admin
    # instead of being released. This records the admin's decision; the "waiting"
    # state itself is derived (deadline passed, no decision), so it can never go
    # stale. escalated_at is only the moment admins were told, so they hear once.
    timeout_review = models.CharField(
        max_length=10, choices=TIMEOUT_REVIEW_CHOICES, default=TIMEOUT_NONE, editable=False
    )
    timeout_note = models.TextField(blank=True, editable=False)
    timeout_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="timeout_decisions", editable=False,
    )
    timeout_decided_at = models.DateTimeField(null=True, blank=True, editable=False)
    escalated_at = models.DateTimeField(null=True, blank=True, editable=False)
    # An admin having read a request that reached donors unverified. It changes
    # nothing for donors; it only takes the request off the admin's own list, so
    # two admins don't review the same thing twice.
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="checked_requests",
    )
    checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["blood_type"]),
        ]

    def __str__(self):
        return f"{self.blood_type} for {self.patient_name} at {self.hospital}"

    def save(self, *args, **kwargs):
        # First save: derive the deadline from urgency (unless one was given explicitly).
        if self.expires_at is None:
            self.expires_at = timezone.now() + timedelta(hours=URGENCY_HOURS[self.urgency])
        # Decided here, at the moment of creation, so no way of creating a request
        # (the form, the Django admin, a shell) can skip the review.
        if self._state.adding and self.extra_review == EXTRA_NONE and self.exceeds_unit_limit:
            self.extra_review = EXTRA_PENDING
        super().save(*args, **kwargs)

    @property
    def exceeds_unit_limit(self):
        """Asks for more units than the standard limit currently allows."""
        return self.units_needed > max_units_per_request()

    @property
    def is_awaiting_extra_review(self):
        return self.extra_review == EXTRA_PENDING

    @property
    def was_extra_reviewed(self):
        return self.extra_review in (EXTRA_APPROVED, EXTRA_REJECTED)

    @property
    def is_expired(self):
        """Only a still-Pending request can expire; a Fulfilled one stays Fulfilled."""
        return (
            self.status == STATUS_PENDING
            and self.expires_at is not None
            and timezone.now() >= self.expires_at
        )

    @property
    def display_status(self):
        """Pending / Fulfilled / Expired: the status people should see."""
        return STATUS_EXPIRED if self.is_expired else self.status

    @property
    def is_open(self):
        """Still waiting for a donor."""
        return self.status == STATUS_PENDING and not self.is_expired

    @property
    def hospital_deadline(self):
        """When the hospital must have verified this by, or it goes to an admin.

        The wait depends on urgency and is set from the admin panel, so this reads
        it rather than hard-coding a number. None before the first save, because
        created_at isn't set yet.
        """
        if self.created_at is None:
            return None
        # An approved over-limit request waited for the admin, not for the
        # hospital, so the hospital's window starts when the admin approved.
        start = self.reviewed_at if (self.extra_review == EXTRA_APPROVED and self.reviewed_at) else self.created_at
        return start + timedelta(minutes=wait_minutes_for(self.urgency))

    @property
    def hospital_wait_over(self):
        """The hospital's wait has run out (so an admin may now decide)."""
        deadline = self.hospital_deadline
        return deadline is not None and timezone.now() >= deadline

    @property
    def extra_accepted_by_hospital(self):
        """The hospital verified an over-limit request, which accepts its extra units too."""
        return (
            self.extra_review == EXTRA_APPROVED and self.is_verified
            and bool(self.reviewed_by_id) and self.reviewed_by_id == self.verified_by_id
            and not self.verified_by_admin
        )

    @property
    def needs_timeout_review(self):
        """The hospital missed its deadline and no admin has decided yet.

        This is the queue an admin works through. It is the instance twin of
        selectors.awaiting_timeout_review().
        """
        if self.status != STATUS_PENDING or self.is_expired:
            return False
        if self.extra_review in (EXTRA_PENDING, EXTRA_REJECTED):
            return False  # waiting for the admin for a different reason
        if self.is_verified or self.released_early or self.timeout_review != TIMEOUT_NONE:
            return False
        deadline = self.hospital_deadline
        return deadline is not None and timezone.now() >= deadline

    @property
    def verified_by_admin(self):
        """True when an admin, not the hospital's own desk, verified it."""
        return bool(self.verified_by_id) and self.verified_by.is_staff

    @property
    def verified_label(self):
        return gettext("Verified by admin") if self.verified_by_admin else gettext("Verified by hospital")

    @property
    def release_label(self):
        """Why donors can see this when no hospital verified it, or "" if verified
        or not released. The wording is fixed so it never reads as verification."""
        if self.is_verified or not self.released_early:
            return ""
        return gettext(ADMIN_APPROVED_LABEL if self.timeout_review == TIMEOUT_APPROVED else ADMIN_RELEASED_LABEL)

    @property
    def was_checked_by_nobody(self):
        """Released by an admin without a hospital verifying it and without an
        admin reading it since. This is the admin panel's "unchecked" list.
        """
        return not self.is_verified and self.checked_at is None and self.released_early

    @property
    def requester_is_blocked(self):
        """True if an admin has blocked whoever posted this."""
        from accounts.models import UserBlock

        return UserBlock.objects.filter(user_id=self.requester_id).exists()

    @property
    def is_visible_to_donors(self):
        """The single rule for 'can donors see and act on this'.

        Every page and query uses this (or its queryset twin in selectors.py) so
        the board, the detail page and the respond check can never disagree.

        A blocked poster's request fails here whatever its verification state, so
        blocking someone takes their open requests off the board at once instead
        of only stopping the next one.
        """
        if self.requester_is_blocked:
            return False
        if self.extra_review in (EXTRA_PENDING, EXTRA_REJECTED):
            return False
        return self.is_verified or self.released_early


class DonorResponse(models.Model):
    """A donor tapping 'I can donate' on a request."""

    request = models.ForeignKey(BloodRequest, on_delete=models.CASCADE, related_name="responses")
    donor = models.ForeignKey(
        "donors.DonorProfile", on_delete=models.CASCADE, related_name="responses"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # When the donor tapped "I've reached the hospital". Empty until they do.
    arrived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One response per donor per request, enforced by the database itself.
            models.UniqueConstraint(
                fields=["request", "donor"], name="unique_response_per_donor_request"
            ),
        ]

    def __str__(self):
        return f"{self.donor} -> request #{self.request_id}"


class Report(models.Model):
    """A user flagging a request as suspicious, for an admin to review."""

    request = models.ForeignKey(BloodRequest, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_made")
    reason = models.CharField(max_length=30, choices=REPORT_REASON_CHOICES)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One report per person per request - resubmitting doesn't pile up duplicates.
            models.UniqueConstraint(fields=["request", "reporter"], name="unique_report_per_reporter_request"),
        ]

    def __str__(self):
        return f"{self.reason} - request #{self.request_id}"
