"""Every change the admin panel can make goes through a function here.

Each one does the work and writes the audit entry in the same transaction, so an
action can never happen without leaving a record, and a failed action cannot
leave a record of something that did not happen. Views call these; views never
write to the models directly.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from accounts.identity import retire_identity
from accounts.models import UserBlock
from blood_requests.models import BloodRequest, Report
from core.constants import (
    EXTRA_APPROVED,
    EXTRA_PENDING,
    EXTRA_REJECTED,
    STATUS_PENDING,
    STATUS_REJECTED,
    TIMEOUT_APPROVED,
    TIMEOUT_REJECTED,
    URGENCY_HOURS,
)
from blood_requests.services import announce_if_visible
from notifications import services as notes
from notifications.models import Notification
from siteadmin.models import AdminAction, SiteSetting


def _log(actor, action, target="", note=""):
    return AdminAction.objects.create(
        actor=actor,
        # Copied, not looked up later: the username has to stay readable in the
        # log even if the account is renamed or removed.
        actor_name=getattr(actor, "username", "") or "unknown",
        action=action,
        target=target[:200],
        note=note,
    )


def _describe(blood_request):
    return f"Request {blood_request.pk} ({blood_request.patient_name}, {blood_request.blood_type})"


def _can_still_change(blood_request):
    """A request an admin may still verify or release: open, and not held back by
    the extra-units review (that has its own decision)."""
    return (
        blood_request.status == STATUS_PENDING
        and blood_request.extra_review not in (EXTRA_PENDING, EXTRA_REJECTED)
    )


@transaction.atomic
def verify_request(actor, blood_request, note=""):
    """Mark a request verified, as a hospital would.

    For when the admin has checked by other means - a phone call to the ward -
    and the hospital's own desk is not going to act. It is a stronger claim than
    "admin released", so the audit entry records who made it. Returns False and
    changes nothing if the request is closed or already verified.
    """
    if blood_request.is_verified or not _can_still_change(blood_request):
        return False
    blood_request.is_verified = True
    blood_request.verified_by = actor
    blood_request.verified_at = timezone.now()
    blood_request.save(update_fields=["is_verified", "verified_by", "verified_at"])
    _log(actor, AdminAction.VERIFIED_REQUEST, _describe(blood_request), note)
    notes.notify(
        blood_request.requester, Notification.HOSPITAL_VERIFIED,
        f"{blood_request.patient_name}'s request was verified by an admin. Donors can see it now.",
        blood_request,
    )
    announce_if_visible(blood_request.pk)
    return True


@transaction.atomic
def review_timeout(actor, blood_request, approve, note=""):
    """Decide on a request whose hospital missed its deadline.

    Approving lets donors see it, labelled "Admin approved - not hospital
    verified"; it never sets is_verified. Rejecting closes it for good. Both tell
    the requester. Returns False, and changes nothing, if the request is not
    waiting for this decision (already decided, verified in the meantime, closed
    or expired), so two admins pressing the button cannot contradict each other.
    """
    blood_request = type(blood_request).objects.select_for_update().get(pk=blood_request.pk)
    if not blood_request.needs_timeout_review:
        return False
    now = timezone.now()
    blood_request.timeout_decided_by = actor
    blood_request.timeout_decided_at = now
    blood_request.timeout_note = note
    if approve:
        blood_request.timeout_review = TIMEOUT_APPROVED
        blood_request.released_early = True
        blood_request.released_by = actor
        blood_request.released_at = now
        # Read by an admin as part of deciding, so it does not reappear as "unchecked".
        blood_request.checked_by = actor
        blood_request.checked_at = now
        # Donors could not see it while it waited, so the window starts now.
        blood_request.expires_at = max(
            blood_request.expires_at, now + timedelta(hours=URGENCY_HOURS[blood_request.urgency])
        )
        action = AdminAction.APPROVED_TIMEOUT
    else:
        blood_request.timeout_review = TIMEOUT_REJECTED
        blood_request.status = STATUS_REJECTED
        action = AdminAction.REJECTED_TIMEOUT
    blood_request.save(update_fields=[
        "timeout_review", "timeout_note", "timeout_decided_by", "timeout_decided_at", "released_early",
        "released_by", "released_at", "checked_by", "checked_at", "expires_at", "status",
    ])
    _log(actor, action, _describe(blood_request), note)
    if approve:
        notes.notify(
            blood_request.requester, Notification.ADMIN_APPROVED,
            f"An admin approved {blood_request.patient_name}'s request. Donors can see it, "
            "marked as not verified by the hospital.",
            blood_request,
        )
        announce_if_visible(blood_request.pk)
    else:
        notes.notify(
            blood_request.requester, Notification.ADMIN_REJECTED,
            f"An admin rejected {blood_request.patient_name}'s request."
            + (f" Note: {note}" if note else ""),
            blood_request,
        )
    return True


@transaction.atomic
def mark_request_checked(actor, blood_request, note=""):
    """Record that a person has looked at a request that went out unverified.

    It is the admin equivalent of clearing an inbox: the request stays exactly as
    it is, but it leaves the "nobody checked this" list so the next admin does not
    look at it again.
    """
    blood_request.checked_by = actor
    blood_request.checked_at = timezone.now()
    blood_request.save(update_fields=["checked_by", "checked_at"])
    _log(actor, AdminAction.CHECKED_REQUEST, _describe(blood_request), note)
    return blood_request


@transaction.atomic
def remove_request(actor, blood_request, note=""):
    """Delete a request that should not be on the site.

    The description is built BEFORE the delete, because afterwards there is
    nothing left to describe - which is the whole reason the audit log stores the
    target as text rather than a foreign key.
    """
    target = _describe(blood_request)
    blood_request.delete()
    _log(actor, AdminAction.REMOVED_REQUEST, target, note)
    return target


@transaction.atomic
def resolve_report(actor, report, note=""):
    report.resolved = True
    report.save(update_fields=["resolved"])
    target = f"Report {report.pk} on request {report.request_id} ({report.reason})"
    _log(actor, AdminAction.RESOLVED_REPORT, target, note)
    return report


@transaction.atomic
def block_user(actor, user, note=""):
    """Stop a user posting or offering to help. Their open requests leave the
    board at once, because open_requests() and is_visible_to_donors both check
    for a block.

    Idempotent: blocking someone already blocked changes nothing and writes no
    second entry, so a double-clicked button does not fill the log.
    """
    block, created = UserBlock.objects.get_or_create(
        user=user, defaults={"reason": note, "blocked_by": actor}
    )
    if not created:
        return block
    open_count = BloodRequest.objects.filter(requester=user, status="Pending").count()
    target = f"{user.username}"
    if open_count:
        target = f"{user.username} ({open_count} open request(s) pulled from the board)"
    _log(actor, AdminAction.BLOCKED_USER, target, note)
    return block


@transaction.atomic
def delete_user(actor, user, note=""):
    """Permanently remove a donor or patient account and everything that hangs off it.

    The donor profile, CNIC fingerprint, requests they posted (with the offers on them),
    their offers on other people's requests, notifications and any block all go with the
    account. The audit log keeps one line with the username and how much was removed,
    and nothing else about the person: no phone, CNIC or health answers.
    """
    role = "donor" if hasattr(user, "donor_profile") else "patient only"
    posted = BloodRequest.objects.filter(requester=user).count()
    target = f"{user.username} ({role}, {posted} request(s) removed)"
    retire_identity(user)      # the CNIC cannot be used to make a new account
    user.delete()
    _log(actor, AdminAction.DELETED_USER, target, note)


@transaction.atomic
def unblock_user(actor, user, note=""):
    """Lift a block. Also idempotent, for the same reason."""
    deleted, _ = UserBlock.objects.filter(user=user).delete()
    if not deleted:
        return False
    _log(actor, AdminAction.UNBLOCKED_USER, user.username, note)
    return True


@transaction.atomic
def save_wait_times(actor, critical, urgent, normal, note="", max_units=None):
    """Change the three auto-approve windows, and optionally the unit limit.

    The old values go in the audit entry, so the log answers "what was it before
    someone changed it?" without needing a second table of history.
    """
    row = SiteSetting.load()
    before = (
        f"was {row.critical_wait_minutes}/{row.urgent_wait_minutes}/{row.normal_wait_minutes} min"
        f", {row.max_units_per_request} units"
    )
    row.critical_wait_minutes = critical
    row.urgent_wait_minutes = urgent
    row.normal_wait_minutes = normal
    if max_units is not None:
        row.max_units_per_request = max_units
    row.updated_by = actor
    row.save()
    _log(
        actor,
        AdminAction.CHANGED_SETTINGS,
        f"Critical {critical} min, Urgent {urgent} min, Normal {normal} min, "
        f"{row.max_units_per_request} units per request",
        note or before,
    )
    return row


@transaction.atomic
def review_extra_units(actor, blood_request, approve, note):
    """Decide on a request that asked for more than the standard unit limit.

    An admin only gets here once the hospital's wait has run out without it
    verifying (a hospital that verifies accepts the extra units itself). So
    approving also lets donors see the request, labelled as admin-approved and
    not hospital-verified, the same as approving a timed-out request. Its
    deadline restarts, because donors could not see it while it waited.

    Rejecting closes it for good; the requester sees the note.
    Returns False, and changes nothing, if there is nothing to decide.
    """
    if blood_request.extra_review != EXTRA_PENDING:
        return False
    now = timezone.now()
    blood_request.reviewed_by = actor
    blood_request.reviewed_at = now
    blood_request.review_note = note
    if approve:
        blood_request.extra_review = EXTRA_APPROVED
        window = now + timedelta(hours=URGENCY_HOURS[blood_request.urgency])
        blood_request.expires_at = max(blood_request.expires_at, window)
        if not blood_request.is_verified:
            blood_request.released_early = True
            blood_request.released_by = actor
            blood_request.released_at = now
            blood_request.checked_by = actor
            blood_request.checked_at = now
            blood_request.timeout_review = TIMEOUT_APPROVED
            blood_request.timeout_decided_by = actor
            blood_request.timeout_decided_at = now
        action = AdminAction.APPROVED_EXTRA_UNITS
    else:
        blood_request.extra_review = EXTRA_REJECTED
        blood_request.status = STATUS_REJECTED
        action = AdminAction.REJECTED_EXTRA_UNITS
    blood_request.save(update_fields=[
        "extra_review", "status", "review_note", "reviewed_by", "reviewed_at", "expires_at",
        "released_early", "released_by", "released_at", "checked_by", "checked_at",
        "timeout_review", "timeout_decided_by", "timeout_decided_at",
    ])
    _log(actor, action, f"{_describe(blood_request)}, {blood_request.units_needed} units", note)
    if approve:
        notes.notify(
            blood_request.requester, Notification.EXTRA_APPROVED,
            f"An admin approved {blood_request.units_needed} units for {blood_request.patient_name}.",
            blood_request,
        )
        announce_if_visible(blood_request.pk)
    else:
        notes.notify(
            blood_request.requester, Notification.EXTRA_REJECTED,
            f"An admin did not approve {blood_request.units_needed} units for {blood_request.patient_name}."
            + (f" Note: {note}" if note else ""),
            blood_request,
        )
    return True
