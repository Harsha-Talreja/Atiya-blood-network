from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from blood_requests.selectors import requests_for_donor
from blood_requests.services import can_record_donation, sidelined_reason
from core.blood import compatible_recipient_types
from core.constants import BLOOD_TYPES
from core.flash import success_dialog
from core.models import Location
from donors.forms import DonorProfileForm
from donors.models import DonorProfile
from donors.selectors import search_donors
from django.utils.translation import gettext, gettext_lazy as _
from django.utils.formats import date_format

RING_LENGTH = 326.73        # circumference of the progress ring in the template (2 * pi * 52)
DASHBOARD_REQUESTS = 4


def _donor_of(user):
    return DonorProfile.objects.select_related("location").filter(user=user).first()


def _wants_json(request):
    return "application/json" in request.headers.get("accept", "")


def greeting_for(hour):
    """'Good morning' / 'Good afternoon' / 'Good evening' for an hour 0-23.

    Pure on purpose: the view passes in the hour, so the boundaries can be
    tested without faking the clock."""
    if hour < 12:
        return gettext("Good morning")
    if hour < 17:
        return gettext("Good afternoon")
    return gettext("Good evening")


@login_required
def profile(request):
    donor = _donor_of(request.user)
    if donor is None:
        return redirect("donors:edit")
    # One queryset, used twice: the first few rows to show, and the whole count
    # for the number in the sidebar and the summary tile.
    # The side panel has two entries, "Requests for you" and "My details"; each
    # opens its own page (?tab=...). Anything else falls back to the requests.
    tab = request.GET.get("tab")
    tab = tab if tab in ("requests", "details") else "requests"
    sidelined = sidelined_reason(donor)
    matching = requests_for_donor(donor).none() if sidelined else requests_for_donor(donor)
    return render(request, "donors/profile.html", {
        "sidelined": sidelined,
        "can_record_donation": can_record_donation(donor),
        "tab": tab,
        "dash_active": f"donor-{tab}",
        "donor": donor,
        "today": timezone.localdate(),
        "ring_offset": round(RING_LENGTH * (1 - donor.cooldown_progress / 100), 2),
        "matching_requests": list(matching[:DASHBOARD_REQUESTS]) if tab == "requests" else [],
        "matching_total": matching.count(),
        "greeting": greeting_for(timezone.localtime().hour),
        "first_name": donor.full_name.split()[0] if donor.full_name.split() else donor.full_name,
        "can_give_to": len(compatible_recipient_types(donor.blood_type)),
    })


@login_required
def edit(request):
    donor = _donor_of(request.user)
    form = DonorProfileForm(request.POST or None, instance=donor, user=request.user)
    saved = None
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.user = request.user          # always the signed-in person, never taken from the form
        try:
            # The CNIC and the profile are saved together, so one is never left without the other.
            with transaction.atomic():
                form.save_identity()
                saved.save()
        except ValidationError as problem:
            form.add_error("cnic", problem)
            saved = None
    if saved is not None:
        if donor is None:
            success_dialog(request, gettext("You're a donor now"), gettext("Thank you, %(name)s. Matching requests will appear on your dashboard.") % {"name": saved.full_name})
        else:
            messages.success(request, gettext("Your donor profile has been updated."))
            return redirect(reverse("donors:profile") + "?tab=details")
        return redirect("donors:profile")
    return render(request, "donors/edit.html", {"form": form, "editing": donor is not None})


@login_required
@require_POST
def toggle_availability(request):
    donor = _donor_of(request.user)
    if donor is None:
        return JsonResponse({"error": "no profile"}, status=404) if _wants_json(request) else redirect("donors:edit")
    donor.is_available = not donor.is_available
    donor.save(update_fields=["is_available"])
    if _wants_json(request):
        return JsonResponse({"available": donor.is_available})
    messages.success(request, gettext("You are now available to donate.") if donor.is_available else gettext("You are now marked as not available."))
    return redirect("donors:profile")


@login_required
@require_POST
def donated_today(request):
    donor = _donor_of(request.user)
    if donor is None:
        return redirect("donors:edit")
    today = timezone.localdate()
    if donor.last_donation_date == today:
        messages.info(request, gettext("You've already recorded a donation for today."))
        return redirect("donors:profile")
    if not can_record_donation(donor):
        messages.error(request, gettext("You can record a donation after you offer to help a request. Open a request and tap \"I can help\" first."))
        return redirect("donors:profile")
    donor.last_donation_date = today
    donor.save(update_fields=["last_donation_date"])
    messages.success(request, gettext("Thank you for donating. You can donate again on %(date)s.") % {"date": date_format(donor.next_eligible_date, "d F Y")})
    return redirect("donors:profile")


@login_required
def search(request):
    """Search available, eligible donors by the patient's blood type and city."""
    blood_type = request.GET.get("blood_type", "")
    city = request.GET.get("city", "")
    has_searched = bool(blood_type or city)

    donors = search_donors(blood_type=blood_type or None, city=city or None) if has_searched else []

    return render(request, "donors/search.html", {
        "dash_active": "request-find",
        "donors": donors,
        "blood_types": BLOOD_TYPES,
        "cities": Location.objects.values_list("city", flat=True).distinct().order_by("city"),
        "selected_blood_type": blood_type,
        "selected_city": city,
        "has_searched": has_searched,
    })
