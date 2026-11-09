"""Account-level models.

The project uses Django's own User model, so anything extra about a user lives
here as its own table rather than in a custom user model.
"""

from django.conf import settings
from django.db import models


class UserBlock(models.Model):
    """A user an admin has stopped from using the site.

    The row existing IS the block - there is no boolean to fall out of step with
    it, and unblocking deletes the row. The history of both actions lives in the
    audit log (siteadmin.AdminAction), which is append-only, so deleting the row
    loses nothing we need to answer for.

    A block is a lock-out: the person cannot sign in, anyone already signed in
    is signed out on their next click (core.middleware), and their open requests
    leave the donor board at once. Unblocking restores the account as it was.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="block"
    )
    reason = models.TextField(blank=True)
    # SET_NULL: removing an admin account must not quietly lift everyone's block.
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="blocks_made",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "blocked user"
        verbose_name_plural = "blocked users"

    def __str__(self):
        return f"{self.user.username} (blocked)"


class Identity(models.Model):
    """The CNIC a person gave, kept as a fingerprint and the last four digits.

    One row per account, saved once from either the donor form or the request
    form. The number itself is not stored: only a keyed hash (so the same CNIC
    cannot be used on a second account) and its last four digits (so the person
    and an admin can recognise it). Nothing here says the CNIC was checked with
    NADRA, because it was not: it is a length-checked number the person typed.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="identity"
    )
    cnic_hash = models.CharField(max_length=64, unique=True)
    last4 = models.CharField(max_length=4)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "identity"
        verbose_name_plural = "identities"

    def __str__(self):
        return f"{self.user.username} (CNIC ending {self.last4})"

    @property
    def masked(self):
        return "\u2022" * 9 + self.last4


class RetiredCnic(models.Model):
    """The fingerprint of a CNIC whose account an admin deleted.

    So a deleted account cannot simply be remade with the same CNIC. Only the keyed
    fingerprint is kept: no name, no username, no last four digits, nothing that says
    whose it was. A superuser can remove a row in /admin/ if a block was a mistake.
    """

    cnic_hash = models.CharField(max_length=64, unique=True)
    retired_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "retired CNIC"
        verbose_name_plural = "retired CNICs"

    def __str__(self):
        return f"CNIC fingerprint {self.cnic_hash[:8]}\u2026 (account deleted)"


def is_blocked(user):
    """True if this user is currently blocked.

    Safe to call with an anonymous user, which keeps the callers in views free of
    is_authenticated checks they would otherwise need first.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return UserBlock.objects.filter(user=user).exists()


def needs_strict_session(user):
    """True for accounts that can see or change other people's data: the site
    admin (staff) and hospital desk accounts. They are always signed out when the
    browser closes and after a short time without use (core.middleware)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or user.is_superuser:
        return True
    return hasattr(user, "hospital_account")
