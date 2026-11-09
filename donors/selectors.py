"""Reusable read-only donor queries."""
from django.db.models import Count, Q

from core.blood import compatible_donor_types
from core.constants import BLOOD_TYPES
from donors.eligibility import eligibility_cutoff
from donors.models import DonorProfile


def ready_donor_counts():
    """Donors who are available AND out of their cooldown, counted per blood type.

    Always returns all eight blood types (zeros included) as a list of
    (blood_type, count) pairs, in the standard display order.
    """
    cutoff = eligibility_cutoff()
    rows = (
        DonorProfile.objects.filter(is_available=True)
        .filter(Q(last_donation_date__isnull=True) | Q(last_donation_date__lte=cutoff))
        .values("blood_type")
        .annotate(total=Count("id"))
    )
    counts = {row["blood_type"]: row["total"] for row in rows}
    return [(blood_type, counts.get(blood_type, 0)) for blood_type in BLOOD_TYPES]


def newest_ready_donors(limit=3):
    """The newest donors who are available and out of their cooldown.

    Only the three things the public live box shows: blood type, city and when
    they joined. No names, phones or ids leave this function.
    """
    cutoff = eligibility_cutoff()
    return list(
        DonorProfile.objects.filter(is_available=True)
        .filter(Q(last_donation_date__isnull=True) | Q(last_donation_date__lte=cutoff))
        .order_by("-created_at")
        .values("blood_type", "location__city", "created_at")[:limit]
    )


def search_donors(blood_type=None, city=None):
    """Available, eligible donors, optionally filtered by the patient's blood type
    (only donors compatible with that type are returned) and/or city.

    Unlike matching.find_matching_donors, this isn't tied to a specific request -
    it's a general lookup, e.g. for a hospital or requester browsing ahead of time.
    """
    cutoff = eligibility_cutoff()
    donors = (
        DonorProfile.objects.filter(is_available=True)
        .filter(Q(last_donation_date__isnull=True) | Q(last_donation_date__lte=cutoff))
        .select_related("user", "location")
    )
    if blood_type in BLOOD_TYPES:
        donors = donors.filter(blood_type__in=compatible_donor_types(blood_type))
    if city:
        donors = donors.filter(location__city=city)
    return donors.order_by("-created_at", "-pk")  # newest first
