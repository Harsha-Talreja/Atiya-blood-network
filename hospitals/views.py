from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from blood_requests.models import BloodRequest
from blood_requests.services import StatusConflict, escalate_overdue_requests, verify_by_hospital
from core.charts import requests_per_day
from hospitals.models import HospitalAccount

RECENT_VERIFIED_LIMIT = 8


def _hospital_account_of(user):
    if not user.is_authenticated:
        return None
    return HospitalAccount.objects.select_related("hospital", "hospital__location").filter(user=user).first()


@login_required
def dashboard(request):
    """A hospital's own view of requests routed to it: what's waiting on them,
    and what they've already verified recently."""
    account = _hospital_account_of(request.user)
    if account is None:
        messages.error(request, gettext("This account isn't linked to a hospital."))
        return redirect("core:home")
    escalate_overdue_requests()

    base = BloodRequest.objects.filter(hospital=account.hospital).select_related("location", "requester")
    unverified = base.filter(is_verified=False, status="Pending").order_by("-created_at")
    pending = unverified.exclude(requester_id=request.user.pk)

    week_ago = timezone.now() - timedelta(days=7)
    this_week = base.filter(created_at__gte=week_ago)
    # Requests that passed this hospital's deadline without it verifying them
    # (they went to an admin). This is the number the dashboard exists to bring
    # down, so it is shown plainly rather than buried in a list.
    missed = this_week.filter(is_verified=False, escalated_at__isnull=False).count()

    return render(request, "hospitals/dashboard.html", {
        "dash_active": "desk",
        "account": account,
        # A staff member can't verify their own request (see `verify` below), so it's kept
        # separate here rather than showing a Verify button that would just be rejected.
        "pending": pending,
        "own_pending": unverified.filter(requester_id=request.user.pk),
        "recently_verified": base.filter(is_verified=True).order_by("-verified_at")[:RECENT_VERIFIED_LIMIT],
        "kpi_waiting": pending.count(),
        "kpi_week": this_week.count(),
        "kpi_verified_week": this_week.filter(is_verified=True).count(),
        "kpi_missed": missed,
        "trend": requests_per_day(base, days=7),
    })


@login_required
@require_POST
def verify(request, pk):
    account = _hospital_account_of(request.user)
    if account is None:
        raise PermissionDenied(gettext("This account isn't linked to a hospital."))

    blood_request = get_object_or_404(BloodRequest, pk=pk)
    if blood_request.hospital_id != account.hospital_id:
        raise PermissionDenied(gettext("This request belongs to a different hospital."))
    if blood_request.requester_id == request.user.pk:
        raise PermissionDenied(gettext("You can't verify a request you posted yourself. Ask another staff member to verify it."))

    try:
        changed = verify_by_hospital(request.user, blood_request.pk)
    except StatusConflict as conflict:
        messages.error(request, str(conflict))
        return redirect("hospitals:dashboard")
    if changed:
        blood_request.refresh_from_db()
        messages.success(request, gettext("Verified. %(patient)s's request is now visible to donors.")
                         % {"patient": blood_request.patient_name})
    return redirect("hospitals:dashboard")
