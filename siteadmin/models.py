"""Two models the admin panel owns: the settings it can change, and the record
of everything it has done.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.constants import (
    AUTO_APPROVE_MINUTES_BY_URGENCY,
    AUTO_APPROVE_MINUTES_MAX,
    AUTO_APPROVE_MINUTES_MIN,
    DEFAULT_MAX_UNITS_PER_REQUEST,
    MAX_UNITS_LIMIT_MAX,
    MAX_UNITS_LIMIT_MIN,
    URGENCY_CRITICAL,
    URGENCY_NORMAL,
    URGENCY_URGENT,
)

_WINDOW_BOUNDS = [
    MinValueValidator(AUTO_APPROVE_MINUTES_MIN),
    MaxValueValidator(AUTO_APPROVE_MINUTES_MAX),
]


class SiteSetting(models.Model):
    """The settings an admin can change without editing code. Exactly one row.

    The row is created on first read, using the defaults in core.constants, so a
    fresh database behaves the same as before this model existed.
    """

    # Minutes a request waits for its hospital before it goes to an admin for a decision.
    critical_wait_minutes = models.PositiveSmallIntegerField(
        default=AUTO_APPROVE_MINUTES_BY_URGENCY[URGENCY_CRITICAL], validators=_WINDOW_BOUNDS
    )
    urgent_wait_minutes = models.PositiveSmallIntegerField(
        default=AUTO_APPROVE_MINUTES_BY_URGENCY[URGENCY_URGENT], validators=_WINDOW_BOUNDS
    )
    normal_wait_minutes = models.PositiveSmallIntegerField(
        default=AUTO_APPROVE_MINUTES_BY_URGENCY[URGENCY_NORMAL], validators=_WINDOW_BOUNDS
    )
    # Units one request may ask for before it needs an admin's approval.
    max_units_per_request = models.PositiveSmallIntegerField(
        default=DEFAULT_MAX_UNITS_PER_REQUEST,
        validators=[MinValueValidator(MAX_UNITS_LIMIT_MIN), MaxValueValidator(MAX_UNITS_LIMIT_MAX)],
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="site_settings_changes",
    )

    class Meta:
        verbose_name = "site setting"
        verbose_name_plural = "site settings"

    def __str__(self):
        return "Site settings"

    @classmethod
    def load(cls):
        """The one row, created with the code defaults if it is not there yet."""
        row, _ = cls.objects.get_or_create(pk=1)
        return row

    def wait_minutes(self):
        """{urgency: minutes}, in the shape the request code wants."""
        return {
            URGENCY_CRITICAL: self.critical_wait_minutes,
            URGENCY_URGENT: self.urgent_wait_minutes,
            URGENCY_NORMAL: self.normal_wait_minutes,
        }

    def save(self, *args, **kwargs):
        # There is one settings row and its id is 1. Pinning it here means a
        # second row cannot be created by accident, from a fixture or a shell.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Site settings cannot be deleted, only changed.")


class AdminAction(models.Model):
    """One line in the audit log: who did what, to what, and why.

    Written by siteadmin.services, never by a view directly, so an admin action
    cannot be added later that forgets to leave a record. Nothing in the panel
    edits or deletes these rows - the log is only ever appended to.
    """

    VERIFIED_REQUEST = "Verified a request"
    RELEASED_REQUEST = "Sent a request to donors early"
    CHECKED_REQUEST = "Marked a request checked"
    REMOVED_REQUEST = "Removed a request"
    RESOLVED_REPORT = "Resolved a report"
    BLOCKED_USER = "Blocked a user"
    UNBLOCKED_USER = "Unblocked a user"
    DELETED_USER = "Deleted a user"
    CHANGED_SETTINGS = "Changed the waiting times"
    APPROVED_EXTRA_UNITS = "Approved extra units"
    REJECTED_EXTRA_UNITS = "Rejected extra units"
    APPROVED_TIMEOUT = "Approved a timed-out request"
    REJECTED_TIMEOUT = "Rejected a timed-out request"

    ACTION_CHOICES = [
        (VERIFIED_REQUEST, VERIFIED_REQUEST),
        (RELEASED_REQUEST, RELEASED_REQUEST),
        (CHECKED_REQUEST, CHECKED_REQUEST),
        (REMOVED_REQUEST, REMOVED_REQUEST),
        (RESOLVED_REPORT, RESOLVED_REPORT),
        (BLOCKED_USER, BLOCKED_USER),
        (UNBLOCKED_USER, UNBLOCKED_USER),
        (DELETED_USER, DELETED_USER),
        (CHANGED_SETTINGS, CHANGED_SETTINGS),
        (APPROVED_EXTRA_UNITS, APPROVED_EXTRA_UNITS),
        (REJECTED_EXTRA_UNITS, REJECTED_EXTRA_UNITS),
        (APPROVED_TIMEOUT, APPROVED_TIMEOUT),
        (REJECTED_TIMEOUT, REJECTED_TIMEOUT),
    ]

    # SET_NULL, not CASCADE: deleting an admin account must not erase the record
    # of what that account did. actor_name keeps the username readable either way.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="admin_actions",
    )
    actor_name = models.CharField(max_length=150)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    # The target is stored as plain text, not a foreign key, because the thing it
    # points at is often the thing that was just removed. A row that says
    # "Removed request 38 (Ahmed Khan)" has to survive request 38 being gone.
    target = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["-created_at"])]
        verbose_name = "admin action"

    def __str__(self):
        return f"{self.actor_name}: {self.action} - {self.target}"
