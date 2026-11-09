"""Read-only queries the admin panel needs.

Kept apart from the views so each page is "fetch, then render", and so the
numbers on the overview can be tested without going through a request.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q
from django.utils import timezone

from accounts.models import UserBlock
from blood_requests.models import BloodRequest, Report
from blood_requests.selectors import (
    awaiting_extra_review,
    awaiting_timeout_review,
    open_requests,
    still_with_hospital,
    unchecked_requests,
)
from core.constants import EXTRA_PENDING, STATUS_FULFILLED, STATUS_PENDING
from donors.eligibility import eligibility_cutoff
from donors.models import DonorProfile
from hospitals.models import Hospital

User = get_user_model()

# How low a blood type has to be before the panel calls it short. Three or fewer
# ready donors is not a supply - one of them travelling or falling ill empties it.
SHORT_SUPPLY_AT = 3


def oldest_unchecked_age():
    """How long the oldest unreviewed request has been waiting, or None.

    This is the number that grows when nobody is minding the site, which is why
    the overview prints it next to the count. A count alone looks the same on a
    quiet day as it does after a week of neglect.
    """
    oldest = unchecked_requests().order_by("created_at").values_list("created_at", flat=True).first()
    return None if oldest is None else timezone.now() - oldest


def supply_rows():
    """(blood_type, ready_count, percent_of_the_largest, is_short) per type.

    The bar is drawn relative to the biggest count rather than to a fixed target,
    because the project has no stock target - it has people. A full bar means
    "the most we have of anything", not "enough".
    """
    from donors.selectors import ready_donor_counts

    counts = ready_donor_counts()
    biggest = max((count for _, count in counts), default=0)
    # Red is only worth printing when it singles something out. On a small
    # network every type is under the threshold, and eight red marks say nothing
    # except "this site is new" - which the section header says once, in words.
    # So a type is short only when the network is big enough for the gap to be a
    # real imbalance rather than its overall size.
    network_has_spread = biggest > SHORT_SUPPLY_AT
    rows = []
    for blood_type, count in counts:
        percent = 0 if biggest == 0 else round(count / biggest * 100)
        rows.append(
            {
                "blood_type": blood_type,
                "count": count,
                "percent": percent,
                "is_short": network_has_spread and count <= SHORT_SUPPLY_AT,
            }
        )
    # Most plentiful first, so the short types collect at the end where the eye
    # lands last and the red marks sit together.
    rows.sort(key=lambda row: (-row["count"], row["blood_type"]))
    return rows


def overview_numbers():
    """The four figures at the foot of the overview, plus the counts in the header."""
    now = timezone.now()
    this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ready = (
        DonorProfile.objects.filter(is_available=True)
        .filter(Q(last_donation_date__isnull=True) | Q(last_donation_date__lte=eligibility_cutoff()))
        .count()
    )
    return {
        "unchecked": unchecked_requests().count(),
        "oldest_unchecked": oldest_unchecked_age(),
        "open_reports": Report.objects.filter(resolved=False).count(),
        "open_requests": open_requests().count(),
        "fulfilled_this_month": BloodRequest.objects.filter(
            status=STATUS_FULFILLED, fulfilled_at__gte=this_month
        ).count(),
        "went_out_unchecked": BloodRequest.objects.filter(
            created_at__gte=this_month, is_verified=False
        ).count(),
        "expired_unfilled": BloodRequest.objects.filter(
            status=STATUS_PENDING, expires_at__lt=now
        ).exclude(extra_review=EXTRA_PENDING).count(),
        "awaiting_extra": awaiting_extra_review().count(),
        "awaiting_timeout": awaiting_timeout_review().count(),
        "donors_total": DonorProfile.objects.count(),
        "donors_ready": ready,
        "users_total": ordinary_users().count(),
        "blocked_total": UserBlock.objects.count(),
        "hospitals_total": Hospital.objects.count(),
    }


def sidebar_counts():
    """The small numbers beside each side-panel item.

    One query each, and they are what tells an admin whether a page is worth
    opening - so the panel does not need a row of stat boxes repeating them.
    """
    return {
        "requests": open_requests().count(),
        "donors": DonorProfile.objects.count(),
        "users": ordinary_users().count(),
        "reports": Report.objects.filter(resolved=False).count(),
        "hospitals": Hospital.objects.count(),
        "review": awaiting_extra_review().count(),
        "timeout": awaiting_timeout_review().count(),
    }


def needs_a_person(limit=6):
    """The overview's first list: what a human actually has to look at.

    Ordered by report count first, then newest, because a request other people
    have already flagged deserves attention before one nobody has complained
    about.
    """
    return (
        unchecked_requests()
        .select_related("hospital", "hospital__location", "requester")
        .annotate(report_count=Count("reports", filter=Q(reports__resolved=False)))
        .order_by("-report_count", "-created_at")[:limit]
    )


def requests_page(state="all", query=""):
    """The Requests page, filtered by one of the tabs across the top."""
    now = timezone.now()
    rows = BloodRequest.objects.select_related("hospital", "hospital__location", "requester")
    # A request still inside its hospital's wait is the hospital's to handle. It
    # reaches the admin only when that wait runs out (the Timed out tab).
    rows = rows.exclude(pk__in=still_with_hospital().values("pk"))

    if state == "unchecked":
        rows = rows.filter(pk__in=unchecked_requests().values("pk"))
    elif state == "live":
        rows = rows.filter(pk__in=open_requests().values("pk"))
    elif state == "fulfilled":
        rows = rows.filter(status=STATUS_FULFILLED)
    elif state == "expired":
        rows = rows.filter(status=STATUS_PENDING, expires_at__lt=now).exclude(extra_review=EXTRA_PENDING)
    elif state == "review":
        rows = rows.filter(pk__in=awaiting_extra_review().values("pk"))
    elif state == "timeout":
        rows = rows.filter(pk__in=awaiting_timeout_review().values("pk"))

    if query:
        rows = rows.filter(
            Q(patient_name__icontains=query)
            | Q(hospital__name__icontains=query)
            | Q(requester__username__icontains=query)
        )
    # Newest first, so a request that has just arrived is the first row, not the last.
    return rows.annotate(report_count=Count("reports", filter=Q(reports__resolved=False))).order_by("-created_at", "-pk")


def donors_page(state="all", query="", blood_type=""):
    rows = DonorProfile.objects.select_related("user", "location")
    cutoff = eligibility_cutoff()
    eligible = Q(last_donation_date__isnull=True) | Q(last_donation_date__lte=cutoff)

    if state == "ready":
        rows = rows.filter(eligible, is_available=True)
    elif state == "resting":
        rows = rows.filter(is_available=True).exclude(eligible)
    elif state == "unavailable":
        rows = rows.filter(is_available=False)

    # Exact match, not a search: this comes from clicking a mark on the supply
    # strip, where "A+" must not also bring back "AB+".
    if blood_type:
        rows = rows.filter(blood_type=blood_type)

    if query:
        rows = rows.filter(
            Q(full_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(location__city__icontains=query)
        )
    return rows.order_by("-created_at", "-pk")  # newest first


def ordinary_users():
    """The accounts the Users page is about: donors and patients.

    Staff and hospital logins are left out on purpose. They are not people an
    admin judges by their posts, and neither can be blocked from the panel.
    """
    return User.objects.filter(is_staff=False, hospital_account__isnull=True)


def users_page(state="all", query=""):
    """Every donor and patient account, with the two numbers that matter for judging one: how much
    they have posted, and how many unresolved reports name their posts.
    """
    rows = ordinary_users().select_related("block", "donor_profile").annotate(
        posted=Count("blood_requests", distinct=True),
        reports_against=Count(
            "blood_requests__reports",
            filter=Q(blood_requests__reports__resolved=False),
            distinct=True,
        ),
        last_posted=Max("blood_requests__created_at"),
        # Sorting key only: 1 if this account is blocked, 0 if not.
        blocked=Count("block"),
    )

    if state == "reported":
        rows = rows.filter(reports_against__gt=0)
    elif state == "blocked":
        rows = rows.filter(block__isnull=False)

    if query:
        rows = rows.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(donor_profile__full_name__icontains=query)
        )
    # Newest account first, so someone who has just signed up is the first row. Reported and
    # blocked accounts are one tab away ("Reported", "Blocked"), and the overview counts them.
    return rows.order_by("-date_joined", "-pk")


def reports_page(state="unresolved"):
    rows = Report.objects.select_related(
        "request", "request__hospital", "request__requester", "reporter"
    ).annotate(
        poster_report_count=Count(
            "request__requester__blood_requests__reports",
            filter=Q(request__requester__blood_requests__reports__resolved=False),
            distinct=True,
        )
    )
    if state == "unresolved":
        rows = rows.filter(resolved=False)
    elif state == "resolved":
        rows = rows.filter(resolved=True)
    return rows


def hospitals_page():
    """Hospitals, with how many requests are sitting unverified at each desk.

    A hospital with a growing number here is the reason requests are reaching
    donors unchecked, so this column is how an admin finds out who to ring.
    """
    now = timezone.now()
    return (
        Hospital.objects.select_related("location")
        .annotate(
            waiting=Count(
                "blood_requests",
                filter=Q(
                    blood_requests__is_verified=False,
                    blood_requests__status=STATUS_PENDING,
                    blood_requests__expires_at__gt=now,
                ),
                distinct=True,
            ),
            verified_total=Count(
                "blood_requests", filter=Q(blood_requests__is_verified=True), distinct=True
            ),
        )
        .order_by("-waiting", "-pk")
    )
