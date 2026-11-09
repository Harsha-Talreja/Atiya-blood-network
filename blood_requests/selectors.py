"""Reusable read-only queries for blood requests (used by several pages)."""
from datetime import timedelta

from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.utils import timezone

from blood_requests.models import BloodRequest, DonorResponse
from blood_requests.visibility import wait_minutes
from core.blood import compatible_recipient_types
from core.constants import (
    EXTRA_APPROVED,
    EXTRA_NONE,
    EXTRA_PENDING,
    EXTRA_REJECTED,
    STATUS_PENDING,
    TIMEOUT_NONE,
    URGENCY_CRITICAL,
    URGENCY_URGENT,
)


def open_requests():
    """Requests donors can actually see: Pending, not past their deadline, posted
    by someone who is not blocked, and either verified by their hospital or
    released by an admin.

    This is the queryset twin of BloodRequest.is_visible_to_donors - keep the two
    in step. It feeds the public board, the home page and donor matching. A
    request whose hospital has not verified it is invisible everywhere except to
    its own requester, the hospital and staff, until an admin lets it out; the
    clock alone never does (see awaiting_timeout_review).
    """
    now = timezone.now()
    return BloodRequest.objects.filter(
        Q(is_verified=True) | Q(released_early=True),
        status=STATUS_PENDING,
        expires_at__gt=now,
        # LEFT JOIN on accounts.UserBlock: no block row means not blocked.
        requester__block__isnull=True,
    ).exclude(
        # Over the unit limit and not yet accepted: the hospital verifying it or an
        # admin approving it makes it visible, nothing else does.
        extra_review__in=[EXTRA_PENDING, EXTRA_REJECTED]
    )


def _past_hospital_deadline():
    """Q for "the hospital's wait is over", per urgency (admin-editable minutes)."""
    now = timezone.now()
    past_deadline = Q()
    for urgency, minutes in wait_minutes().items():
        cutoff = now - timedelta(minutes=minutes)
        # An approved over-limit request starts its wait when the admin approved.
        past_deadline |= Q(urgency=urgency, extra_review=EXTRA_NONE, created_at__lte=cutoff)
        past_deadline |= Q(urgency=urgency, extra_review=EXTRA_APPROVED, reviewed_at__lte=cutoff)
        # An over-limit request waits for its hospital like any other: the admin only
        # gets it once that wait has run out.
        past_deadline |= Q(urgency=urgency, extra_review=EXTRA_PENDING, created_at__lte=cutoff)
    return past_deadline


def still_with_hospital():
    """Requests that are the hospital's to decide and that admins should not see yet.

    Pending, unverified, not released, and still inside the hospital's wait. The
    moment the wait runs out they leave this set and appear in
    awaiting_timeout_review() instead, so a request is always in exactly one of
    the two. Over-limit requests waiting for an admin are not here: those are
    the admin's from the start.
    """
    now = timezone.now()
    return BloodRequest.objects.filter(
        status=STATUS_PENDING,
        expires_at__gt=now,
        is_verified=False,
        released_early=False,
        timeout_review=TIMEOUT_NONE,
        extra_review__in=[EXTRA_NONE, EXTRA_APPROVED, EXTRA_PENDING],
    ).exclude(_past_hospital_deadline())


def awaiting_timeout_review():
    """Requests whose hospital missed its deadline and that no admin has decided.

    The queryset twin of BloodRequest.needs_timeout_review, newest first
    by creation time. They are not visible to donors; an admin approves or rejects.
    """
    now = timezone.now()
    past_deadline = Q()
    for urgency, minutes in wait_minutes().items():
        cutoff = now - timedelta(minutes=minutes)
        # An approved over-limit request starts its wait when the admin approved.
        past_deadline |= Q(urgency=urgency, extra_review=EXTRA_NONE, created_at__lte=cutoff)
        past_deadline |= Q(urgency=urgency, extra_review=EXTRA_APPROVED, reviewed_at__lte=cutoff)
    return (
        BloodRequest.objects.filter(
            past_deadline,
            status=STATUS_PENDING,
            expires_at__gt=now,
            is_verified=False,
            released_early=False,
            timeout_review=TIMEOUT_NONE,
            requester__block__isnull=True,
        )
        .select_related("hospital", "hospital__location", "requester")
        .order_by("-created_at")
    )


def awaiting_extra_review():
    """Over-limit requests an admin has not decided yet, newest first.

    Only once the hospital's wait has run out: a hospital that verifies in time
    accepts the extra units itself, so the admin never needs to see those.
    """
    return (
        BloodRequest.objects.filter(extra_review=EXTRA_PENDING, status=STATUS_PENDING)
        .filter(Q(is_verified=True) | _past_hospital_deadline())
        .select_related("hospital", "hospital__location", "requester")
        .order_by("-created_at")
    )


def unchecked_requests():
    """Open requests an admin released that no hospital verified and no admin has
    read since.

    The queryset twin of BloodRequest.was_checked_by_nobody. An admin letting a
    request out early is a deliberate trade of verification for speed, so this
    list is where a second pair of eyes catches a fake post.
    """
    return open_requests().filter(is_verified=False, checked_at__isnull=True)


def most_urgent_first(queryset):
    """Order Critical, then Urgent, then Normal; newest first inside each group."""
    urgency_rank = Case(
        When(urgency=URGENCY_CRITICAL, then=Value(0)),
        When(urgency=URGENCY_URGENT, then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )
    return queryset.annotate(urgency_rank=urgency_rank).order_by("urgency_rank", "-created_at")


def requests_for_donor(donor):
    """Open requests this donor could give to: compatible type, same city, not their own post.

    Used on the donor dashboard, so it only needs to be "good enough" - the full,
    exhaustive compatibility check lives in matching.find_matching_donors (the other
    direction: given a request, find donors).
    """
    mine = DonorResponse.objects.filter(donor=donor).values("request_id")
    return most_urgent_first(
        open_requests()
        .filter(
            blood_type__in=compatible_recipient_types(donor.blood_type),
            location__city=donor.location.city,
        )
        .exclude(requester_id=donor.user_id)
        # A request someone else has already offered on is not shown to anyone else. One this
        # donor offered on stays in their list, so they can still reach it.
        .annotate(offer_total=Count("responses"))
        .exclude(Q(offer_total__gt=0) & ~Q(pk__in=mine))
        .select_related("location")
    )
