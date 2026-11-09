"""Creating, counting and clearing notifications. Every other app calls these
functions; none of them writes Notification rows directly."""
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

User = get_user_model()


def _request_url(blood_request):
    return reverse("blood_requests:detail", args=[blood_request.pk]) if blood_request else ""


def notify(user, kind, message, blood_request=None, url=None):
    """Tell one person something. Returns the row, or None if there is nobody to tell."""
    if user is None:
        return None
    return Notification.objects.create(
        user=user,
        kind=kind,
        message=message[:240],
        request=blood_request,
        url=_request_url(blood_request) if url is None else url,
    )


def notify_many(users, kind, message, blood_request=None, url=None):
    """One row per distinct user. A single INSERT, so telling every admin is one query."""
    seen, rows = set(), []
    link = _request_url(blood_request) if url is None else url
    for user in users:
        if user is None or user.pk in seen:
            continue
        seen.add(user.pk)
        rows.append(Notification(user=user, kind=kind, message=message[:240], request=blood_request, url=link))
    return Notification.objects.bulk_create(rows)


def admins():
    """Everyone who works the admin panel: active staff accounts."""
    return User.objects.filter(is_staff=True, is_active=True)


def notify_admins(kind, message, blood_request=None, url=None):
    return notify_many(admins(), kind, message, blood_request, url)


def hospital_staff(hospital):
    """The login accounts that speak for one hospital."""
    from hospitals.models import HospitalAccount

    return [
        account.user
        for account in HospitalAccount.objects.filter(hospital=hospital).select_related("user")
    ]


def unread_count(user):
    if user is None or not user.is_authenticated:
        return 0
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def mark_read(user, pk):
    """Mark one of THIS user's notifications read. Another person's id is ignored,
    so guessing ids reveals and changes nothing. Returns the row or None."""
    note = Notification.objects.filter(user=user, pk=pk).first()
    if note is not None:
        note.mark_read()
    return note


def mark_all_read(user):
    return Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=timezone.now())
