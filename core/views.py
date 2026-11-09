from django.contrib.auth.decorators import login_required
from django.core.cache import caches
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext

from blood_requests.models import BloodRequest
from blood_requests.services import requests_left_today
from blood_requests.selectors import most_urgent_first, open_requests, requests_for_donor
from blood_requests.services import sidelined_reason
from core.blood import COMPATIBLE_DONORS
from core.constants import (
    BLOOD_TYPES,
    DONATION_COOLDOWN_DAYS,
    MAX_REQUESTS_PER_USER_PER_DAY,
    STATUS_FULFILLED,
    STATUS_PENDING,
    URGENCY_HOURS,
)
from core.models import Location
from donors.models import DonorProfile
from donors.selectors import newest_ready_donors, ready_donor_counts
from donors.views import greeting_for
from hospitals.models import HospitalAccount

HOME_REQUEST_LIMIT = 3
LIVE_STRIP_LIMIT = 5
LIVE_FEED_LIMIT = 3


def live_feed(requests, limit=LIVE_FEED_LIMIT):
    """The newest things happening on the network, for the glass box in the hero.

    Requests donors can see and donors who are ready, mixed newest first. Each
    row carries a blood type, a city and a time, nothing that names a person.
    """
    rows = [
        {"kind": "need", "blood_type": r.blood_type, "city": r.location.city, "when": r.created_at}
        for r in requests
    ]
    rows += [
        {"kind": "donor", "blood_type": d["blood_type"], "city": d["location__city"], "when": d["created_at"]}
        for d in newest_ready_donors(limit)
    ]
    rows.sort(key=lambda row: row["when"], reverse=True)
    return rows[:limit]


def home(request):
    latest = most_urgent_first(open_requests().select_related("location"))[:HOME_REQUEST_LIMIT]

    # The strip under the hero buttons: the same requests the board shows,
    # most urgent first, so it can never show something a donor could not see.
    live = most_urgent_first(open_requests().select_related("location", "hospital"))[:LIVE_STRIP_LIMIT]

    # Bars for "donors ready by blood type": widths are relative to the biggest group.
    ready = ready_donor_counts()
    biggest = max((count for _, count in ready), default=0) or 1
    # The bars with the fewest ready donors turn amber, but only when the groups
    # actually differ: with every bar equal there is no "fewest" to point at.
    smallest = min((count for _, count in ready), default=0)
    show_low_key = 0 < smallest < biggest
    availability = [
        {"blood_type": blood_type, "count": count, "percent": round(count * 100 / biggest),
         "low": show_low_key and count == smallest}
        for blood_type, count in ready
    ]

    context = {
        # Totals for the big numbers: remembered for a minute so the busiest page
        # does not recount them for every visitor. (open_count matches the navbar.)
        "donor_count": caches["snap"].get_or_set("bn:donors", lambda: DonorProfile.objects.count(), 60),
        "open_count": caches["snap"].get_or_set("bn:open-count", lambda: open_requests().count(), 20),
        "fulfilled_count": caches["snap"].get_or_set(
            "bn:fulfilled", lambda: BloodRequest.objects.filter(status=STATUS_FULFILLED).count(), 60),
        "city_count": caches["snap"].get_or_set("bn:cities", lambda: Location.objects.values("city").distinct().count(), 60),
        "latest_requests": latest,
        "live_requests": live,
        "live_feed": live_feed(live),
        "availability": availability,
        "show_low_key": show_low_key,
        "ready_total": sum(count for _, count in ready),
        "blood_types": BLOOD_TYPES,
        "compatibility": COMPATIBLE_DONORS,  # drives the compatibility checker widget
    }
    return render(request, "core/home.html", context)


def about(request):
    return render(request, "core/about.html", {
        "SITE_TAGLINE": gettext("Find a blood donor in minutes, not hours"),
        "cooldown": DONATION_COOLDOWN_DAYS,
        "hours": URGENCY_HOURS,
    })


DASHBOARD_REQUESTS = 3


@login_required
def dashboard(request):
    """Where a person lands after signing in: one page for both of their roles.

    The same account can give blood and ask for it, so the overview shows a
    small card for each, and the side panel leads to the full pages. A hospital
    account, like an admin account, has no donor or patient side, so it goes straight to its own desk.
    """
    if request.user.is_staff:
        # An admin has the admin panel and nothing on the donor or patient side.
        return redirect("siteadmin:overview")
    if HospitalAccount.objects.filter(user=request.user).exists():
        return redirect("hospitals:dashboard")

    donor = DonorProfile.objects.select_related("location").filter(user=request.user).first()
    mine = BloodRequest.objects.filter(
        requester=request.user, status=STATUS_PENDING, expires_at__gt=timezone.now()
    ).annotate(offer_count=Count("responses"))
    open_rows = list(mine)

    context = {
        "dash_active": "overview",
        "donor": donor,
        "greeting": greeting_for(timezone.localtime().hour),
        "open_count": len(open_rows),
        "open_offers": sum(row.offer_count for row in open_rows),
        "daily_limit": MAX_REQUESTS_PER_USER_PER_DAY,
        "requests_left": requests_left_today(request.user),
    }
    if donor:
        sidelined = sidelined_reason(donor)
        matching = requests_for_donor(donor).none() if sidelined else requests_for_donor(donor)
        context["sidelined"] = sidelined
        context["matching_total"] = matching.count()
        context["matching_requests"] = list(matching[:DASHBOARD_REQUESTS])
        context["first_name"] = donor.full_name.split()[0] if donor.full_name.split() else donor.full_name
        context["state"] = "paused" if not donor.is_available else "rest" if not donor.is_eligible else "ready"
    else:
        context["first_name"] = request.user.get_username()
    return render(request, "dashboard/overview.html", context)
