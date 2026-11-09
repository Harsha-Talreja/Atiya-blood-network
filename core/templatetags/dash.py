"""The side panel shared by every page of the signed-in dashboard.

One tag, so the panel is built in one place: who is signed in, which role
sections they get, the two small counts, and which entry is the current page.
"""
from django import template
from django.urls import reverse
from django.utils import timezone

from blood_requests.models import BloodRequest
from blood_requests.selectors import requests_for_donor
from blood_requests.services import sidelined_reason
from core.constants import STATUS_PENDING
from donors.models import DonorProfile
from hospitals.models import HospitalAccount

register = template.Library()


def donor_state(donor):
    """('ready' | 'rest' | 'paused', short label) for the chip on the panel."""
    if not donor.is_available:
        return "paused", "Not available"
    if not donor.is_eligible:
        return "rest", "Resting"
    return "ready", "Ready to donate"


def _counts(request):
    """The two numbers shown on the panel and on the page tabs, worked out once per request."""
    cached = getattr(request, "_dash_counts", None)
    if cached is not None:
        return cached
    user = request.user
    donor = DonorProfile.objects.select_related("location").filter(user=user).first()
    counts = {
        "donor": donor,
        "matching": 0 if (donor is None or sidelined_reason(donor)) else requests_for_donor(donor).count(),
        "open": BloodRequest.objects.filter(
            requester=user, status=STATUS_PENDING, expires_at__gt=timezone.now()
        ).count(),
    }
    request._dash_counts = counts
    return counts


@register.inclusion_tag("components/dash_panel.html", takes_context=True)
def dash_panel(context, active=""):
    user = context["request"].user
    account = HospitalAccount.objects.select_related("hospital", "hospital__location").filter(user=user).first()
    panel = {"active": active, "user": user, "account": account, "donor": None}

    if account is not None:
        # A hospital sees only its verification desk: no donor or patient entries.
        panel["waiting"] = (
            BloodRequest.objects.filter(hospital=account.hospital, is_verified=False, status=STATUS_PENDING)
            .exclude(requester_id=user.pk)
            .count()
        )
        panel["name"] = account.hospital.name
        panel["sub"] = "Hospital account"
        return panel

    counts = _counts(context["request"])
    donor = counts["donor"]
    panel["donor"] = donor
    panel["name"] = donor.full_name if donor else user.get_username()
    panel["sub"] = user.get_username() if donor else "Signed in"
    if donor:
        panel["state"], panel["state_label"] = donor_state(donor)
        panel["matching_total"] = counts["matching"]
    panel["open_total"] = counts["open"]
    return panel


@register.inclusion_tag("components/dash_tabs.html", takes_context=True)
def dash_tabs(context, group, current):
    """The row of tabs at the top of a page in the side panel's "Donate blood" or
    "Request blood" section. The panel keeps three plain links; what used to be
    more links is a tab here, on the pages it belongs to."""
    counts = _counts(context["request"])
    if group == "donate":
        label = "Donate blood"
        tabs = [
            ("requests", "Requests for you", reverse("donors:profile") + "?tab=requests", counts["matching"]),
            ("details", "My details", reverse("donors:profile") + "?tab=details", 0),
        ]
    else:
        label = "Request blood"
        tabs = [
            ("mine", "My requests", reverse("blood_requests:mine"), counts["open"]),
            ("new", "Post a request", reverse("blood_requests:new"), 0),
            ("find", "Find donors", reverse("donors:search"), 0),
        ]
    return {"label": label, "current": current,
            "tabs": [{"key": k, "label": text, "url": url, "count": n} for k, text, url, n in tabs]}
