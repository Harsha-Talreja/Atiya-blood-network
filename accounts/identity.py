"""Saving and checking the CNIC people give on the donor and request forms."""
import hashlib
import hmac

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import Identity, RetiredCnic
from django.utils.translation import gettext, gettext_lazy as _


def cnic_fingerprint(cnic):
    """A keyed hash of the 13 digits. Same CNIC, same fingerprint; the digits cannot be read back."""
    return hmac.new(settings.SECRET_KEY.encode(), cnic.encode(), hashlib.sha256).hexdigest()


def get_identity(user):
    """The user's saved identity, or None. Safe for anonymous users."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return Identity.objects.filter(user=user).first()


def has_identity(user):
    return get_identity(user) is not None


RETIRED_MESSAGE = _("This CNIC belonged to an account that an admin removed, so it cannot be used again. "
                   "If you think this is a mistake, please contact an admin.")


def cnic_taken_by_someone_else(cnic, user):
    return Identity.objects.filter(cnic_hash=cnic_fingerprint(cnic)).exclude(user=user).exists()


def cnic_is_retired(cnic):
    """True if the account that used this CNIC was deleted by an admin."""
    return RetiredCnic.objects.filter(cnic_hash=cnic_fingerprint(cnic)).exists()


def retire_identity(user):
    """Keep the fingerprint of this user's CNIC (if they gave one), just before the account is deleted."""
    identity = get_identity(user)
    if identity is not None:
        RetiredCnic.objects.get_or_create(cnic_hash=identity.cnic_hash)


def save_identity(user, cnic):
    """Save the CNIC for this user once. Raises ValidationError if another account already uses it.

    Called inside the same transaction as the profile or request it belongs to, so
    nothing half-saved is left if it fails.
    """
    existing = get_identity(user)
    if existing is not None:
        return existing
    if cnic_is_retired(cnic):
        raise ValidationError(gettext(RETIRED_MESSAGE), code="cnic_retired")
    try:
        with transaction.atomic():
            return Identity.objects.create(user=user, cnic_hash=cnic_fingerprint(cnic), last4=cnic[-4:])
    except IntegrityError:
        raise ValidationError(gettext("This CNIC is already used by another account."), code="cnic_taken") from None
