"""Find donors for a request. One database query, no per-donor lookups."""
from django.db.models import Case, F, IntegerField, Q, Value, When

from core.blood import compatible_donor_types
from donors.eligibility import eligibility_cutoff
from donors.models import DonorProfile


def find_matching_donors(blood_request):
    """Return a QuerySet of DonorProfile that can give to `blood_request`.

    Filters (all in SQL): compatible blood type, available, out of cooldown,
    same city, and not the requester's own profile.
    Order: same area first, then longest time since last donation
    (people who have never donated count as "longest" and come first).
    """
    cutoff = eligibility_cutoff()  # last_donation_date <= cutoff  <=>  cooldown over

    return (
        DonorProfile.objects.filter(
            blood_type__in=compatible_donor_types(blood_request.blood_type),
            is_available=True,
            location__city=blood_request.location.city,
        )
        .filter(Q(last_donation_date__isnull=True) | Q(last_donation_date__lte=cutoff))
        .exclude(user_id=blood_request.requester_id)
        .select_related("user", "location")  # JOINs, so templates add no extra queries
        .annotate(
            area_rank=Case(
                When(location_id=blood_request.location_id, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("area_rank", F("last_donation_date").asc(nulls_first=True), "id")
    )
